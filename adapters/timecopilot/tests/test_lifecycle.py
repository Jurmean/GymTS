"""Real owned sleep processes; no model, Agent, native forecasting or GPU."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from gymts import GymTSError
from gymts_timecopilot.runtime import TimeCopilotRuntime


def alive(pid):
    try:
        state = (Path("/proc") / str(pid) / "stat").read_text().split(")", 1)[1].strip().split()[0]
        return state not in {"Z", "X"}
    except FileNotFoundError:
        return False


def stop_group(group):
    if group is not None:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux worker parent-death protection")
class LifecycleTests(unittest.TestCase):
    def wait_dead(self, pids):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and any(alive(pid) for pid in pids):
            time.sleep(.02)
        self.assertFalse(any(alive(pid) for pid in pids), "Only the owned fixture processes must exit")

    def parent_termination(self, sig):
        worker = (
            "from gymts_timecopilot.worker import arm_parent_death;"
            "import json,os,subprocess,time;arm_parent_death();"
            "child=subprocess.Popen(['sleep','120']);"
            "print(json.dumps([os.getpid(),child.pid,os.getpgrp(),os.getsid(0)]),flush=True);"
            "time.sleep(120)"
        )
        supervisor = (
            "import os,subprocess,sys;"
            "env=dict(os.environ,GYMTS_TIMECOPILOT_PARENT_PID=str(os.getpid()));"
            "worker=subprocess.Popen([sys.executable,'-I','-B','-c',sys.argv[1]],env=env,start_new_session=True);"
            "worker.wait()"
        )
        unrelated = subprocess.Popen(["sleep", "120"], start_new_session=True)
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", supervisor, worker],
                                   stdout=subprocess.PIPE, text=True)
        group = None
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                self.assertTrue(selector.select(10), "Owned worker must become ready without native imports")
            worker_pid, child_pid, group, session = json.loads(process.stdout.readline())
            self.assertEqual(worker_pid, group)
            self.assertEqual(worker_pid, session)
            process.send_signal(sig)
            process.wait(timeout=5)
            self.wait_dead((worker_pid, child_pid))
            self.assertIsNone(unrelated.poll(), "Unrelated process group must remain alive")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            stop_group(group)
            process.stdout.close()
            unrelated.kill()
            unrelated.wait(timeout=5)

    def test_host_sigkill_stops_worker_and_its_child_only(self):
        self.parent_termination(signal.SIGKILL)

    def test_host_sigterm_stops_worker_and_its_child_only(self):
        self.parent_termination(signal.SIGTERM)

    def test_parent_exit_before_arming_cannot_leave_an_orphan(self):
        with tempfile.TemporaryDirectory(prefix="gymts-timecopilot-parent-race-") as directory:
            arm = Path(directory) / "arm"
            survived = Path(directory) / "must-not-exist"
            worker = "\n".join((
                "from gymts_timecopilot.worker import arm_parent_death",
                "import pathlib,sys,time",
                "while not pathlib.Path(sys.argv[1]).exists(): time.sleep(.01)",
                "arm_parent_death()",
                "pathlib.Path(sys.argv[2]).write_text('incorrectly survived')",
            ))
            supervisor = (
                "import os,subprocess,sys;"
                "env=dict(os.environ,GYMTS_TIMECOPILOT_PARENT_PID=str(os.getpid()));"
                "worker=subprocess.Popen([sys.executable,'-I','-B','-c',sys.argv[1],*sys.argv[2:]],"
                "env=env,start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                "print(worker.pid,flush=True)"
            )
            result = subprocess.run([sys.executable, "-I", "-B", "-c", supervisor, worker,
                                     str(arm), str(survived)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            worker_pid = int(result.stdout.strip())
            try:
                # The actual parent has exited before the worker is allowed to arm prctl.
                arm.touch()
                self.wait_dead((worker_pid,))
                self.assertFalse(survived.exists())
            finally:
                stop_group(worker_pid)

    def test_guard_rejects_shared_session_without_signalling_it(self):
        script = (
            "import os;os.environ['GYMTS_TIMECOPILOT_PARENT_PID']=str(os.getppid());"
            "from gymts_timecopilot.worker import arm_parent_death;"
            "arm_parent_death()"
        )
        result = subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertIn("adapter-owned session", result.stderr)

    def test_runtime_cleans_children_even_if_group_leader_already_exited(self):
        original_popen = subprocess.Popen
        with tempfile.TemporaryDirectory(prefix="gymts-timecopilot-lifecycle-") as directory:
            receipt = Path(directory) / "owned.json"
            script = (
                "import json,os,pathlib,subprocess,sys;"
                "child=subprocess.Popen(['sleep','120'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getpid(),child.pid]));"
                "raise SystemExit(1)"
            )
            def launch(command, **kwargs):
                # Exercise the real Runtime's Popen/finally path with a CPU-only failure fixture.
                return original_popen([sys.executable, "-I", "-B", "-c", script, str(receipt)], **kwargs)
            runtime = TimeCopilotRuntime({"repository": "/not-opened", "python": sys.executable}, timeout_seconds=10)
            group = None
            try:
                with patch("gymts_timecopilot.runtime.subprocess.Popen", side_effect=launch):
                    with self.assertRaises(GymTSError):
                        runtime.invoke({"mode": "explicit-lifecycle-fixture"})
                worker_pid, child_pid = json.loads(receipt.read_text())
                group = worker_pid
                self.wait_dead((worker_pid, child_pid))
            finally:
                if group is None and receipt.exists():
                    group = json.loads(receipt.read_text())[0]
                stop_group(group)


if __name__ == "__main__":
    unittest.main()
