"""Linux lifetime binding for the adapter-owned native process group."""
import ctypes
import os
import runpy
import signal
import sys


def arm_parent_death():
    expected = os.environ.get("GYMTS_AREAL_PARENT_PID")
    if expected is None or not sys.platform.startswith("linux"):
        return
    if os.getpgrp() != os.getpid() or os.getsid(0) != os.getpid():
        raise RuntimeError("AReaL parent-death binding requires its own isolated session")
    def stop_owned_group(_signal, _frame):
        os.killpg(os.getpid(), signal.SIGKILL)
    # SIGTERM remains available for the native Trainer's graceful context cleanup.
    signal.signal(signal.SIGUSR1, stop_owned_group)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGUSR1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot bind the owned native group to its coordinator")
    if os.getppid() != int(expected):
        stop_owned_group(signal.SIGUSR1, None)


def main():
    arm_parent_death()
    module = sys.argv[1]
    sys.argv = [module, *sys.argv[2:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
