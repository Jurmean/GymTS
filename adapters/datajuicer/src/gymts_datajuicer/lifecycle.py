"""Linux parent-death cleanup for an adapter-owned isolated worker session."""
import ctypes
import os
import signal
import sys


def arm_parent_death():
    expected = os.environ.get("GYMTS_DATAJUICER_PARENT_PID")
    if expected is None or not sys.platform.startswith("linux"):
        return
    expected = int(expected)
    # Never address a shared or inherited process group. Both launchers use
    # start_new_session=True; the worker must still lead exactly that session.
    if os.getpgrp() != os.getpid() or os.getsid(0) != os.getpid():
        raise RuntimeError("Parent-death cleanup requires an adapter-owned session")
    def stop_owned_group(signum, frame):
        os.killpg(os.getpid(), signal.SIGKILL)
    signal.signal(signal.SIGTERM, stop_owned_group)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot install worker parent-death cleanup")
    # Close the race where the parent exits before prctl is armed.
    if os.getppid() != expected:
        stop_owned_group(signal.SIGTERM, None)
