"""Deadline-bounded evaluator-owned directory/path preparation.

Only tiny receipts cross the process boundary.  Filesystem operations happen
in a disposable process group, so a blocked mount or directory operation can
be terminated without allowing the caller to report a late success.
"""

from __future__ import annotations

import json
import math
import os
import select
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from subprocess import Popen as _Popen

from .l1_budget import BudgetExhausted
from .l1_failures import InspectionFailure
from .l1_request import prepare_request

WORKER = Path(__file__).with_name("l1_parent_io_worker.py")
CLEANUP_SECONDS = 2.0
RECEIPT_LIMIT = 4096
PROTOCOL = "l1-parent-io-v1"
COPY_MAX_BYTES = 256 * 1024 * 1024
TREE_MAX_BYTES = 512 * 1024 * 1024
TREE_MAX_FILES = 4096
TREE_MAX_DEPTH = 32
TREE_MAX_FILE_BYTES = 256 * 1024 * 1024


def _clock() -> float:
    """Use a real monotonic-compatible clock when callers inject a logical one."""
    monotonic = time.monotonic()
    performance = time.perf_counter()
    return performance if abs(monotonic - performance) > 100_000 else monotonic


def _effective_deadline(deadline: float) -> float:
    """Translate synthetic caller deadlines for real worker processes.

    Unit/state-machine tests may replace ``time.monotonic`` in the parent
    process with a small logical clock. The worker is a fresh process and still
    observes the host's real monotonic clock, so passing that synthetic value
    would reject every operation immediately. Production clocks differ by far
    less than this guard and retain the original absolute deadline.
    """
    monotonic = time.monotonic()
    performance = time.perf_counter()
    if abs(monotonic - performance) > 100_000 and deadline < performance - 1_000:
        return deadline + (performance - monotonic)
    return deadline


def _command(
    action: str,
    path: Path,
    *,
    prefix: str = "l1-",
    parents: bool = False,
    source_root: Path | None = None,
    files: tuple[str, ...] = (),
    target_files: tuple[str, ...] = (),
    max_bytes: int = COPY_MAX_BYTES,
    max_files: int = TREE_MAX_FILES,
    max_depth: int = TREE_MAX_DEPTH,
    max_file_bytes: int = TREE_MAX_FILE_BYTES,
    deadline: float | None = None,
    executable: str | None = None,
    runner: Path | None = None,
    workspace: Path | None = None,
    resource_roots: tuple[Path, ...] = (),
    beauty: bool = False,
):
    command = [sys.executable, "-I", str(WORKER), "--action", action, "--path", str(path)]
    if prefix != "l1-":
        command += ["--prefix", prefix]
    if parents:
        command.append("--parents")
    if action == "copy_files":
        if source_root is None:
            raise ValueError("copy_files source root required")
        command += ["--source-root", str(source_root), "--max-bytes", str(max_bytes)]
        destinations = target_files or files
        if len(destinations) != len(files):
            raise ValueError("copy source and destination lists must have equal length")
        for relative, destination in zip(files, destinations):
            command += ["--file", relative, "--target-file", destination]
    if action == "audit_tree":
        command += [
            "--max-bytes", str(max_bytes),
            "--max-files", str(max_files),
            "--max-depth", str(max_depth),
            "--max-file-bytes", str(max_file_bytes),
            "--deadline", str(deadline),
        ]
    if action in {"resolve_executable", "prepare_blender_sandbox", "prepare_inspector"}:
        command += ["--executable", executable, "--deadline", str(deadline)]
    if action == "prepare_blender_sandbox":
        command += ["--runner", str(runner), "--workspace", str(workspace)]
    if action == "prepare_inspector":
        command += ["--runner", str(runner)]
        for root in resource_roots:
            command += ["--resource-root", str(root)]
        if beauty:
            command.append("--beauty")
    return command


def _receipt(data: bytes, execution: dict, started: float, deadline: float) -> list[dict]:
    if len(data) > RECEIPT_LIMIT:
        raise ValueError("oversized parent I/O receipt")
    rows = [json.loads(line) for line in data.splitlines()]
    if len(rows) > 2:
        raise ValueError("too many parent I/O receipts")
    for row in rows:
        if (not isinstance(row, dict) or row.get("protocol") != PROTOCOL
                or row.get("pid") != execution["pid"]
                or row.get("process_group") != execution["pid"]):
            raise ValueError("unbound parent I/O receipt")
    if rows:
        first = rows[0]
        if (first.get("phase") != "started"
                or not isinstance(first.get("entered_monotonic"), (int, float))
                or not math.isfinite(first["entered_monotonic"])
                or not started <= first["entered_monotonic"] <= deadline):
            raise ValueError("invalid parent I/O start receipt")
        execution["worker_started"] = first
    if len(rows) == 2:
        last = rows[1]
        if (last.get("phase") != "finished"
                or last.get("status") not in {"completed", "failed"}
                or not isinstance(last.get("completed_monotonic"), (int, float))
                or not math.isfinite(last["completed_monotonic"])
                or not rows[0]["entered_monotonic"] <= last["completed_monotonic"] <= execution["finished_monotonic"]):
            raise ValueError("invalid parent I/O completion receipt")
        execution["worker_result"] = last
    return rows


def _kill(process: subprocess.Popen, execution: dict) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
        execution["group_kill_sent"] = True
    except ProcessLookupError:
        execution["group_kill_sent"] = True
    except OSError as error:
        execution.update(group_kill_sent=False, cleanup_error=type(error).__name__)
    try:
        end = execution.get("worker_cleanup_deadline_monotonic")
        process.wait(timeout=CLEANUP_SECONDS if end is None else max(0.0, end - _clock()))
        execution["leader_reaped"] = True
    except subprocess.TimeoutExpired:
        execution["leader_reaped"] = False
    execution["return_code"] = process.returncode


def run_parent_io(
    action: str,
    path: Path,
    *,
    deadline: float,
    prefix: str = "l1-",
    parents: bool = False,
    source_root: Path | None = None,
    files: tuple[str, ...] = (),
    target_files: tuple[str, ...] = (),
    max_bytes: int = COPY_MAX_BYTES,
    max_files: int = TREE_MAX_FILES,
    max_depth: int = TREE_MAX_DEPTH,
    max_file_bytes: int = TREE_MAX_FILE_BYTES,
    cleanup_deadline: float | None = None,
    executable: str | None = None,
    runner: Path | None = None,
    workspace: Path | None = None,
    resource_roots: tuple[Path, ...] = (),
    beauty: bool = False,
) -> dict:
    if action not in {"ensure_directory", "make_temp_directory", "copy_files", "audit_tree", "resolve_executable", "prepare_blender_sandbox", "prepare_inspector"}:
        raise ValueError("unsupported parent I/O action")
    if action in {"resolve_executable", "prepare_blender_sandbox", "prepare_inspector"} and (
        not isinstance(executable, str) or not executable or "\x00" in executable
        or len(executable.encode("utf-8")) > 2048
    ):
        raise ValueError("bounded nonempty executable name without NUL required")
    if action == "prepare_blender_sandbox" and any(
        not isinstance(value, Path) or "\x00" in str(value) or len(str(value).encode()) > 2048
        for value in (runner, workspace)
    ):
        raise ValueError("bounded sandbox runner and workspace paths required")
    if action == "prepare_inspector" and (
        not isinstance(runner, Path) or type(beauty) is not bool
        or type(resource_roots) is not tuple or len(resource_roots) > 16
        or any(not isinstance(value, Path) or "\x00" in str(value)
               or len(str(value).encode()) > 2048 for value in (runner, *resource_roots))
        or sum(len(str(value).encode()) for value in resource_roots) > 2048
    ):
        raise ValueError("bounded inspector runner/resource paths required")
    if not isinstance(path, Path):
        path = Path(path)
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("finite parent I/O deadline required")
    worker_deadline = _effective_deadline(float(deadline))
    if cleanup_deadline is not None and (
        type(cleanup_deadline) not in (int, float) or not math.isfinite(cleanup_deadline)
        or not deadline <= cleanup_deadline <= deadline + CLEANUP_SECONDS
    ):
        raise ValueError("Parent I/O cleanup must share a bounded caller allowance")
    started = _clock()
    execution = {
        "protocol": "l1-parent-io-execution-v1", "action": action,
        "path": str(path), "status": "not_started", "pid": None,
        "deadline_monotonic": deadline, "cleanup_limit_seconds": CLEANUP_SECONDS,
        "worker_deadline_monotonic": worker_deadline,
        "cleanup_deadline_monotonic": cleanup_deadline,
        "worker_cleanup_deadline_monotonic": (
            _effective_deadline(float(cleanup_deadline)) if cleanup_deadline is not None else None
        ),
        "operation": "exec_process_hard_deadline",
    }
    process = None
    if action in {"resolve_executable", "prepare_blender_sandbox", "prepare_inspector"}:
        execution["requested"] = executable
    if action == "prepare_blender_sandbox":
        execution.update(runner=str(runner), workspace=str(workspace))
    captured = bytearray()
    failure: BaseException | None = None
    try:
        if started >= worker_deadline:
            raise BudgetExhausted("No parent I/O after shared deadline")
        environment = {k: v for k, v in os.environ.items()
                       if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
        if action in {"resolve_executable", "prepare_inspector"} and "HOME" in os.environ:
            environment["HOME"] = os.environ["HOME"]
        process = _Popen(
            _command(
                action,
                path,
                prefix=prefix,
                parents=parents,
                source_root=source_root,
                files=files,
                target_files=target_files,
                max_bytes=max_bytes,
                max_files=max_files,
                max_depth=max_depth,
                max_file_bytes=max_file_bytes,
                deadline=worker_deadline,
                executable=executable,
                runner=runner,
                workspace=workspace,
                resource_roots=resource_roots,
                beauty=beauty,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
        execution.update(status="running", pid=process.pid, process_group=process.pid)
        streams = {process.stdout.fileno(), process.stderr.fileno()}
        for fd in streams:
            os.set_blocking(fd, False)
        while streams:
            remaining = worker_deadline - _clock()
            if remaining <= 0:
                raise BudgetExhausted("Parent I/O exhausted shared deadline")
            ready, _, _ = select.select(list(streams), [], [], min(.05, remaining))
            if not ready:
                continue
            for fd in ready:
                chunk = os.read(fd, RECEIPT_LIMIT + 1 - len(captured))
                if not chunk:
                    streams.remove(fd)
                else:
                        captured.extend(chunk)
                        if len(captured) > RECEIPT_LIMIT:
                            raise ValueError("oversized parent I/O output")
        process.wait(timeout=max(0.0, worker_deadline - _clock()))
        execution["status"] = "completed" if process.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        failure = BudgetExhausted("Parent I/O wait exhausted shared deadline")
    except (OSError, ValueError, RuntimeError, BudgetExhausted, KeyboardInterrupt, SystemExit) as error:
        failure = error
    finally:
        if process is not None:
            _kill(process, execution)
        execution["finished_monotonic"] = _clock()
        execution["elapsed_seconds"] = execution["finished_monotonic"] - started
    try:
        rows = _receipt(bytes(captured), execution, started, worker_deadline)
        if failure is None and (len(rows) != 2 or rows[-1].get("status") != "completed"
                                or execution.get("return_code") != 0
                                or not execution.get("leader_reaped")):
            raise ValueError("parent I/O did not complete")
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        if failure is None:
            failure = error
    if failure is None and _clock() >= worker_deadline:
        failure = BudgetExhausted("Late parent I/O receipt rejected")
    if failure is not None:
        if isinstance(failure, (KeyboardInterrupt, SystemExit)):
            execution["status"] = "interrupted"
            failure.parent_io = execution
            raise failure
        execution["status"] = "budget_exhausted" if isinstance(failure, BudgetExhausted) else "failed"
        code = "PARENT_IO_BUDGET_EXHAUSTED" if isinstance(failure, BudgetExhausted) else "PARENT_IO_FAILED"
        error = InspectionFailure("infrastructure_error", code, type(failure).__name__)
        error.parent_io = execution
        raise error from failure
    result = execution.get("worker_result", {}).get("result")
    if not isinstance(result, dict):
        error = InspectionFailure("infrastructure_error", "PARENT_IO_PROTOCOL_ERROR", "Missing parent I/O result")
        error.parent_io = execution
        raise error
    execution["status"] = "completed"
    return {"protocol": PROTOCOL, "action": action, "result": result, "execution": execution}


def resolve_executable(requested: str, *, deadline: float) -> dict:
    """Bound PATH lookup, expansion, symlink resolution and permission checks.

    This receipt proves an observation before launch, not that exec used the
    same inode. Process creation and caller configuration remain separate
    boundaries. Only a tiny result is decoded in the supervisor.
    """
    receipt = run_parent_io(
        "resolve_executable", Path("."), deadline=deadline,
        executable=requested, cleanup_deadline=deadline + CLEANUP_SECONDS,
    )
    result = receipt["result"]
    if (
        result.get("requested") != requested
        or not isinstance(result.get("path"), str)
        or not result["path"].startswith("/") or "\x00" in result["path"]
        or result.get("executable") is not True
        or result.get("binding") != "prelaunch_observation_not_exec_inode_pin"
        or any(type(result.get(key)) is not int for key in (
            "device", "inode", "mode", "bytes", "mtime_ns", "ctime_ns",
        ))
        or not stat.S_ISREG(result["mode"])
    ):
        error = InspectionFailure("infrastructure_error", "PARENT_IO_PROTOCOL_ERROR", "Invalid launcher result")
        receipt["execution"]["status"] = "failed"
        error.parent_io = receipt["execution"]
        raise error
    return receipt


def ensure_directory(path: Path, *, deadline: float, parents: bool = True,
                     cleanup_deadline: float | None = None) -> dict:
    return run_parent_io("ensure_directory", path, deadline=deadline, parents=parents,
                         cleanup_deadline=cleanup_deadline)


def prepare_blender_sandbox(binary: str, runner: Path, workspace: Path, *, deadline: float) -> dict:
    """Bound optional bwrap discovery and mount observation, not sandbox exec."""
    receipt = run_parent_io(
        "prepare_blender_sandbox", Path("."), deadline=deadline,
        executable=binary, runner=runner, workspace=workspace,
        cleanup_deadline=deadline + CLEANUP_SECONDS,
    )
    result = receipt["result"]
    prefix = result.get("prefix")
    valid = isinstance(prefix, list) and all(isinstance(value, str) and "\x00" not in value for value in prefix)
    if result.get("status") == "declared_only":
        valid = valid and prefix == [] and result.get("reason") == "bwrap_not_found"
    elif result.get("status") == "prepared":
        valid = valid and bool(prefix) and prefix[-1] == "--" and prefix[0] == result.get("launcher", {}).get("path")
        valid = valid and result.get("binding") == "prelaunch_mount_observation_not_isolation_proof"
    else:
        valid = False
    if not valid:
        error = InspectionFailure("infrastructure_error", "PARENT_IO_PROTOCOL_ERROR", "Invalid sandbox preparation")
        receipt["execution"]["status"] = "failed"
        error.parent_io = receipt["execution"]
        raise error
    return receipt


def prepare_inspector(binary: str, runner: Path, *, deadline: float,
                      resource_roots: tuple[Path, ...] = (), beauty: bool = False) -> dict:
    """Observe Blender, worker/resources and optional Xvfb under one deadline."""
    receipt = run_parent_io(
        "prepare_inspector", Path("."), deadline=deadline, executable=binary,
        runner=runner, resource_roots=resource_roots, beauty=beauty,
        cleanup_deadline=deadline + CLEANUP_SECONDS,
    )
    result = receipt["result"]
    launcher, display = result.get("launcher"), result.get("display")
    roots = result.get("material_resource_roots")
    valid = (
        result.get("status") == "prepared" and isinstance(launcher, dict)
        and launcher.get("requested") == binary and launcher.get("executable") is True
        and isinstance(launcher.get("path"), str) and launcher["path"].startswith("/")
        and isinstance(result.get("runner"), str) and result["runner"].startswith("/")
        and result.get("binding") == "prelaunch_observation_not_exec_inode_pin"
        and isinstance(roots, list) and len(roots) == len(resource_roots)
        and all(isinstance(root, str) and root.startswith("/") and root != "/" for root in roots)
        and isinstance(display, dict)
    )
    if valid:
        prefix = display.get("prefix")
        valid = isinstance(prefix, list) and all(isinstance(arg, str) and "\x00" not in arg for arg in prefix)
        if display.get("status") == "prepared":
            xvfb = display.get("launcher")
            valid = valid and beauty and isinstance(xvfb, dict) and xvfb.get("executable") is True
            valid = valid and prefix == [xvfb.get("path"), "-a", "-s", "-screen 0 1280x1024x24"]
        else:
            valid = valid and prefix == [] and display.get("status") == ("not_found" if beauty else "not_required")
    if not valid:
        error = InspectionFailure("infrastructure_error", "PARENT_IO_PROTOCOL_ERROR", "Invalid inspector preparation")
        receipt["execution"]["status"] = "failed"
        error.parent_io = receipt["execution"]
        raise error
    return receipt


def make_temp_directory(parent: Path, *, deadline: float, prefix: str = "l1-") -> dict:
    return run_parent_io("make_temp_directory", parent, deadline=deadline, prefix=prefix)


def copy_regular_files(
    source_root: Path,
    destination_root: Path,
    files: tuple[str, ...],
    *,
    deadline: float,
    target_files: tuple[str, ...] = (),
    max_bytes: int = COPY_MAX_BYTES,
) -> dict:
    """Copy validated regular files in one bounded worker process."""
    if not isinstance(source_root, Path) or not isinstance(destination_root, Path):
        raise TypeError("copy roots must be Path objects")
    if not files or any(not isinstance(value, str) for value in files):
        raise ValueError("copy file list must be nonempty strings")
    if target_files and (
        len(target_files) != len(files)
        or any(not isinstance(value, str) for value in target_files)
    ):
        raise ValueError("copy target list must match source file list")
    return run_parent_io(
        "copy_files",
        destination_root,
        deadline=deadline,
        source_root=source_root,
        files=files,
        target_files=target_files,
        max_bytes=max_bytes,
    )


def audit_directory(
    path: Path,
    *,
    deadline: float,
    max_bytes: int = TREE_MAX_BYTES,
    max_files: int = TREE_MAX_FILES,
    max_depth: int = TREE_MAX_DEPTH,
    max_file_bytes: int = TREE_MAX_FILE_BYTES,
) -> dict:
    """Audit a workspace tree without traversing it in the supervising process."""
    if not isinstance(path, Path):
        raise TypeError("audit path must be a Path")
    return run_parent_io(
        "audit_tree",
        path,
        deadline=deadline,
        max_bytes=max_bytes,
        max_files=max_files,
        max_depth=max_depth,
        max_file_bytes=max_file_bytes,
    )


def write_bounded_json(path: Path, value, *, deadline: float, max_bytes: int = 64 * 1024 * 1024) -> dict:
    """Persist a normal evaluator JSON artifact without a session record.

    Execution metadata uses :class:`JsonPersistence` because it needs a
    phase/cleanup ledger.  Immutable spec/diagnostic artifacts only need the
    same bounded writer and ACK, so keeping this small operation separate
    avoids misclassifying those files as compute phase records.
    """
    return prepare_request(path, value, deadline=deadline, max_bytes=max_bytes,
                           replace=True, cleanup_deadline=deadline)
