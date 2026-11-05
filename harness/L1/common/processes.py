"""One-shot POSIX process-group cleanup shared by L1 workers."""

from __future__ import annotations

import os
import signal
import subprocess


def stop_process_group(process: subprocess.Popen) -> None:
    """Terminate the group and reap its leader even if the leader exits first.

    A child ignoring SIGTERM must not survive a cooperative parent's exit.
    Processes that deliberately create a new session require a stronger OS
    sandbox/cgroup boundary and are outside this process-group guarantee.
    """
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        finally:
            # Always address the group again, not just a still-live leader.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    elif process.poll() is None:  # pragma: no cover - Linux benchmark host
        process.kill()
    process.wait()
