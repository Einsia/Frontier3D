"""Hard workspace quota guard for one evaluator-owned candidate process.

The guard is deliberately a separate process.  It watches only the candidate
workspace and, on a quota violation or shared deadline expiry, kills the
candidate process group before emitting a small, hash-free receipt.  The
supervisor must still validate the receipt and perform the final audit.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import stat
import time
from pathlib import Path

PROTOCOL = "l1-workspace-guard-v1"
POLL_SECONDS = 0.02
PROCESS_CLEANUP_WAIT_SECONDS = 0.25
PROCESS_LIST_LIMIT = 256
_abort_requested = False


class QuotaViolation(ValueError):
    """The candidate workspace exceeded a declared limit."""


def _request_abort(_signum: int, _frame: object) -> None:
    global _abort_requested
    _abort_requested = True


def _emit(value: dict) -> None:
    value = {"protocol": PROTOCOL, "pid": os.getpid(), "process_group": os.getpgrp(), **value}
    data = (json.dumps(value, allow_nan=False, separators=(",", ":")) + "\n").encode()
    if len(data) > 4096:
        raise ValueError("oversized workspace guard receipt")
    os.write(1, data)


def _proc_start_time(pid: int) -> int | None:
    """Return Linux ``/proc/<pid>/stat`` start time for PID reuse checks."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        _comm, suffix = text.rsplit(")", 1)
        fields = suffix.split()
        # ``suffix`` starts at stat field 3 (state); starttime is field 22.
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def _proc_state(pid: int) -> tuple[int, str] | None:
    """Return a PID's start time and Linux state for cleanup verification."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        _comm, suffix = text.rsplit(")", 1)
        fields = suffix.split()
        # suffix starts at field 3: state is field 3 and starttime field 22.
        return int(fields[19]), fields[0]
    except (OSError, ValueError, IndexError):
        return None


def _proc_parent(pid: int) -> int | None:
    """Return the parent PID from procfs, or None when it disappeared."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        _comm, suffix = text.rsplit(")", 1)
        fields = suffix.split()
        # ``suffix`` starts at stat field 3 (state); ppid is field 4.
        return int(fields[1])
    except (OSError, ValueError, IndexError):
        return None


def _descendants(target_pid: int) -> dict[int, int]:
    """Collect live descendants and their start times from procfs.

    This supplements process-group cleanup for a candidate that deliberately
    calls ``setsid()``.  PID start times are retained so a re-used PID is not
    mistaken for the original candidate child.
    """
    if not Path("/proc").is_dir():
        return {}
    parent_map: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        parent = _proc_parent(pid)
        if parent is not None:
            parent_map.setdefault(parent, []).append(pid)
    result: dict[int, int] = {}
    queue = list(parent_map.get(target_pid, ()))
    while queue:
        pid = queue.pop()
        if pid in result:
            continue
        start = _proc_start_time(pid)
        if start is None:
            continue
        result[pid] = start
        queue.extend(parent_map.get(pid, ()))
    return result


def _kill_group(target_pid: int) -> bool:
    try:
        os.killpg(target_pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return True


def _kill_target_and_descendants(target_pid: int, tracked: dict[int, int]) -> dict:
    """Kill the candidate group plus descendants that escaped its group."""
    observed = dict(tracked)
    target_start = _proc_start_time(target_pid)
    observed.update(_descendants(target_pid))
    group_killed = _kill_group(target_pid)
    attempted: list[int] = []
    for pid, start in sorted(observed.items(), reverse=True):
        if _proc_start_time(pid) != start:
            continue
        attempted.append(pid)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            # The final receipt records that this PID could not be addressed;
            # it must not turn a quota failure into a false success.
            pass
    # SIGKILL is asynchronous.  A short bounded wait makes the receipt useful
    # to the supervisor: ``cleanup_ack`` is true only after all matching live
    # descendants have disappeared.  Zombies are reported separately because
    # this guard cannot reap a child owned by another process.
    cleanup_started = time.monotonic()
    target_remaining = False
    remaining_live: list[int] = []
    zombies: list[int] = []
    while True:
        remaining_live = []
        zombies = []
        target_state = _proc_state(target_pid)
        target_remaining = bool(
            target_start is not None
            and target_state is not None
            and target_state[0] == target_start
            and target_state[1].upper() != "Z"
        )
        for pid, start in observed.items():
            state = _proc_state(pid)
            if state is None or state[0] != start:
                continue
            if state[1].upper() == "Z":
                zombies.append(pid)
            else:
                remaining_live.append(pid)
        if not target_remaining and not remaining_live and not zombies:
            break
        if time.monotonic() - cleanup_started >= PROCESS_CLEANUP_WAIT_SECONDS:
            break
        time.sleep(POLL_SECONDS)
    remaining_live.sort()
    zombies.sort()
    observed_ids = sorted(observed)
    attempted_ids = sorted(attempted)
    return {
        "protocol": "l1-process-cleanup-v1",
        "group_killed": group_killed,
        "descendants_observed": observed_ids[:PROCESS_LIST_LIMIT],
        "descendants_observed_count": len(observed_ids),
        "descendants_kill_attempted": attempted_ids[:PROCESS_LIST_LIMIT],
        "descendants_kill_attempted_count": len(attempted_ids),
        "descendants_remaining": remaining_live[:PROCESS_LIST_LIMIT],
        "descendants_remaining_count": len(remaining_live),
        "descendants_zombies": zombies[:PROCESS_LIST_LIMIT],
        "descendants_zombies_count": len(zombies),
        "target_pid": target_pid,
        "target_remaining": target_remaining,
        "cleanup_ack": not target_remaining and not remaining_live and not zombies,
        "cleanup_wait_seconds": time.monotonic() - cleanup_started,
    }


def _target_alive(target_pid: int) -> bool:
    try:
        os.kill(target_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _scan(
    root: Path,
    *,
    max_bytes: int,
    max_files: int,
    max_depth: int,
    max_file_bytes: int,
    deadline: float,
) -> dict:
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise QuotaViolation("workspace root is not a regular directory")
    stack = [(root, 0)]
    total = files = directories = deepest = 0
    while stack:
        if time.monotonic() >= deadline:
            raise TimeoutError("workspace guard deadline exhausted")
        directory, depth = stack.pop()
        deepest = max(deepest, depth)
        with os.scandir(directory) as entries:
            for entry in entries:
                if time.monotonic() >= deadline:
                    raise TimeoutError("workspace guard deadline exhausted")
                entry_info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_info.st_mode):
                    raise QuotaViolation(f"workspace contains symlink: {entry.name}")
                if stat.S_ISDIR(entry_info.st_mode):
                    child_depth = depth + 1
                    if child_depth > max_depth:
                        raise QuotaViolation("workspace directory depth limit exceeded")
                    directories += 1
                    stack.append((Path(entry.path), child_depth))
                    continue
                if not stat.S_ISREG(entry_info.st_mode):
                    raise QuotaViolation(f"workspace contains nonregular entry: {entry.name}")
                files += 1
                if files > max_files:
                    raise QuotaViolation("workspace file limit exceeded")
                if entry_info.st_size > max_file_bytes:
                    raise QuotaViolation("workspace single-file limit exceeded")
                total += entry_info.st_size
                if total > max_bytes:
                    raise QuotaViolation("workspace byte limit exceeded")
    return {
        "bytes": total,
        "files": files,
        "directories": directories,
        "max_depth": deepest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--target-pid", type=int, required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-files", type=int, required=True)
    parser.add_argument("--max-depth", type=int, required=True)
    parser.add_argument("--max-file-bytes", type=int, required=True)
    args = parser.parse_args()
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, _request_abort)
    entered = time.monotonic()
    _emit({
        "phase": "started",
        "entered_monotonic": entered,
        "target_pid": args.target_pid,
        "deadline_monotonic": args.deadline,
    })
    status = "target_exited"
    reason = None
    summary = None
    process_cleanup = None
    tracked_descendants: dict[int, int] = {}
    try:
        while True:
            if _abort_requested:
                status = "aborted"
                reason = "supervisor_abort"
                process_cleanup = _kill_target_and_descendants(
                    args.target_pid, tracked_descendants
                )
                break
            if _target_alive(args.target_pid):
                tracked_descendants.update(_descendants(args.target_pid))
            live_descendants = {
                pid: start for pid, start in tracked_descendants.items()
                if _proc_start_time(pid) == start
            }
            tracked_descendants = live_descendants
            if not _target_alive(args.target_pid) and not live_descendants:
                break
            summary = _scan(
                args.root,
                max_bytes=args.max_bytes,
                max_files=args.max_files,
                max_depth=args.max_depth,
                max_file_bytes=args.max_file_bytes,
                deadline=args.deadline,
            )
            if _abort_requested:
                status = "aborted"
                reason = "supervisor_abort"
                process_cleanup = _kill_target_and_descendants(
                    args.target_pid, tracked_descendants
                )
                break
            if time.monotonic() >= args.deadline:
                status = "deadline_exhausted"
                reason = "workspace guard deadline exhausted"
                process_cleanup = _kill_target_and_descendants(
                    args.target_pid, tracked_descendants
                )
                break
            time.sleep(POLL_SECONDS)
        # A final bounded observation is useful for the supervisor's receipt,
        # but a target that exited is not made successful by it.
        if time.monotonic() < args.deadline:
            summary = _scan(
                args.root,
                max_bytes=args.max_bytes,
                max_files=args.max_files,
                max_depth=args.max_depth,
                max_file_bytes=args.max_file_bytes,
                deadline=args.deadline,
            )
    except QuotaViolation as error:
        status = "quota_exceeded"
        reason = str(error)
        process_cleanup = _kill_target_and_descendants(
            args.target_pid, tracked_descendants
        )
    except TimeoutError as error:
        status = "deadline_exhausted"
        reason = str(error)
        process_cleanup = _kill_target_and_descendants(
            args.target_pid, tracked_descendants
        )
    except (OSError, ValueError) as error:
        status = "guard_failed"
        reason = str(error)[:256]
        process_cleanup = _kill_target_and_descendants(
            args.target_pid, tracked_descendants
        )
    _emit({
        "phase": "finished",
        "status": status,
        "completed_monotonic": time.monotonic(),
        "summary": summary,
        "reason": reason,
        "process_cleanup": process_cleanup,
    })
    return 0 if status in {
        "target_exited", "quota_exceeded", "deadline_exhausted", "aborted"
    } else 1


if __name__ == "__main__":
    raise SystemExit(main())
