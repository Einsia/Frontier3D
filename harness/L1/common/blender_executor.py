"""Run one generated L1 script in an isolated, one-shot Blender process."""

from __future__ import annotations

import json
import os
import resource
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

from src.evaluator.l1_budget import DeadlineBudget
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_parent_io import prepare_blender_sandbox, resolve_executable
from src.render.cli import build_command

from .errors import (
    EXECUTOR_PROCESS_ERROR,
    EXECUTOR_PROTOCOL_ERROR,
    EXECUTOR_TIMEOUT,
    EXECUTOR_UNAVAILABLE,
)
from .process_io import PipeEncodingError, PipeLimitError, communicate_bounded
from .processes import stop_process_group as _kill_tree

_WORKSPACE_GUARD = Path(__file__).resolve().parents[3] / "src" / "evaluator" / "l1_workspace_guard.py"
_DEFAULT_WORKSPACE_LIMITS: dict[str, int] = {
    "max_bytes": 512 * 1024 * 1024,
    "max_files": 4096,
    "max_depth": 32,
    "max_file_bytes": 256 * 1024 * 1024,
}
_GUARD_RECEIPT_LIMIT = 4096
_GUARD_CLEANUP_SECONDS = 2.0


@dataclass(frozen=True)
class Execution:
    status: str
    error_code: str | None
    return_code: int | None
    elapsed_seconds: float
    stdout: str
    stderr: str
    sandbox_status: str = "declared_only"
    resource_limits: dict[str, int | None] | None = None
    rng_trace: dict[str, object] | None = None
    workspace_guard: dict[str, object] | None = None
    launcher_io: dict | None = None
    sandbox_io: dict | None = None


def _finish_workspace_guard(
    guard: subprocess.Popen | None, *, deadline: float
) -> dict[str, object] | None:
    """Collect and bind the guard receipt, allowing bounded cleanup time."""
    if guard is None:
        return None
    captured = b""
    error: BaseException | None = None
    try:
        remaining = min(_GUARD_CLEANUP_SECONDS, max(0.0, deadline - time.monotonic()))
        stdout, _stderr = guard.communicate(timeout=remaining)
        captured = stdout or b""
        if len(captured) > _GUARD_RECEIPT_LIMIT:
            raise ValueError("oversized workspace guard receipt")
    except (OSError, subprocess.TimeoutExpired, ValueError) as caught:
        error = caught
        _kill_tree(guard)
        try:
            stdout, _stderr = guard.communicate(timeout=1.0)
            captured = stdout or b""
        except (OSError, subprocess.TimeoutExpired):
            pass
    rows: list[dict[str, object]] = []
    try:
        for line in captured.splitlines():
            row = json.loads(line)
            if (
                not isinstance(row, dict)
                or row.get("protocol") != "l1-workspace-guard-v1"
                or row.get("pid") != guard.pid
                or row.get("process_group") != guard.pid
            ):
                raise ValueError("unbound workspace guard receipt")
            rows.append(row)
    except (ValueError, TypeError, json.JSONDecodeError) as caught:
        error = error or caught
    if error is not None or len(rows) < 2:
        return {
            "protocol": "l1-workspace-guard-v1",
            "status": "guard_failed",
            "pid": guard.pid,
            "process_group": guard.pid,
            "return_code": guard.returncode,
            "error_type": type(error).__name__ if error is not None else "MissingReceipt",
        }
    result = rows[-1]
    result["return_code"] = guard.returncode
    return result


def _rng_trace(stdout: str) -> dict[str, object] | None:
    prefix = "[l1-rng-trace] "
    for line in reversed(stdout.splitlines()):
        if not line.startswith(prefix):
            continue
        try:
            value = json.loads(line[len(prefix) :])
        except json.JSONDecodeError:
            return {
                "protocol": "l1-rng-trace-v1",
                "status": "invalid",
                "reason": "Runner emitted malformed RNG trace JSON",
            }
        return value if isinstance(value, dict) else {
            "protocol": "l1-rng-trace-v1",
            "status": "invalid",
            "reason": "Runner emitted a non-object RNG trace",
        }
    return None


def run_blender(
    script: Path,
    output: Path,
    working_directory: Path,
    timeout: float,
    blender: Path | None = None,
    extra_env: dict[str, str] | None = None,
    *,
    deadline: float | None = None,
    workspace_limits: dict[str, int] | None = None,
) -> Execution:
    """Execute ``script`` and save ``output``; never follows a stale output."""
    context: dict = {}
    try:
        result = _run_blender(
            script, output, working_directory, timeout, blender, extra_env,
            deadline=deadline, workspace_limits=workspace_limits, context=context,
        )
    except BaseException as error:
        error.launcher_io = context.get("launcher_io")
        error.sandbox_io = context.get("sandbox_io")
        raise
    return replace(result, launcher_io=context.get("launcher_io"), sandbox_io=context.get("sandbox_io"))


def _run_blender(
    script: Path,
    output: Path,
    working_directory: Path,
    timeout: float,
    blender: Path | None,
    extra_env: dict[str, str] | None,
    *,
    deadline: float | None,
    workspace_limits: dict[str, int] | None,
    context: dict,
) -> Execution:

    budget = DeadlineBudget.start(timeout, deadline=deadline)
    started = budget.started

    def expired_before_launch() -> Execution:
        shared = deadline is not None and time.monotonic() >= deadline
        return Execution(
            "budget_exhausted" if shared else "timeout",
            "EXECUTOR_BUDGET_EXHAUSTED" if shared else EXECUTOR_TIMEOUT,
            None, time.monotonic() - started, "", "",
        )

    if budget.exhausted:
        return expired_before_launch()
    requested = str(blender) if blender is not None else os.environ.get("BLENDER_BIN", "blender")
    context["launcher_io"] = {"status": "not_started", "requested": requested, "pid": None}
    try:
        context["launcher_io"] = resolve_executable(requested, deadline=budget.deadline)
        blender_binary = context["launcher_io"]["result"]["path"]
    except (InspectionFailure, OSError, ValueError) as error:
        context["launcher_io"] = getattr(error, "parent_io", context["launcher_io"])
        if budget.exhausted:
            return expired_before_launch()
        return Execution(
            "unavailable",
            EXECUTOR_UNAVAILABLE,
            None,
            time.monotonic() - started,
            "",
            str(error),
        )
    except BaseException as error:
        context["launcher_io"] = getattr(error, "parent_io", context["launcher_io"])
        raise
    try:
        workspace_info = working_directory.lstat()
        script_info = script.lstat() if script.exists() or script.is_symlink() else None
        output_parent_info = output.parent.lstat()
        output_info = output.lstat() if output.exists() or output.is_symlink() else None
    except OSError as error:
        return Execution("process_error", EXECUTOR_PROCESS_ERROR, None, 0.0, "", str(error))
    if (
        working_directory.is_symlink()
        or not stat.S_ISDIR(workspace_info.st_mode)
        or (script_info is not None and (
            script.is_symlink() or not stat.S_ISREG(script_info.st_mode)
        ))
        or output.parent.is_symlink()
        or not stat.S_ISDIR(output_parent_info.st_mode)
        or (output_info is not None and (output.is_symlink() or not stat.S_ISREG(output_info.st_mode)))
    ):
        return Execution(
            "process_error", EXECUTOR_PROCESS_ERROR, None, 0.0, "",
            "candidate script/workspace/output path is not a regular non-symlink path",
        )
    output.unlink(missing_ok=True)
    command = build_command(
        blender_binary,
        script,
        output,
        overwrite=True,
        working_directory=working_directory,
    )
    # Keep command construction inside the shared budget. Path validation is
    # deliberately limited to existing paths so lightweight process doubles
    # can exercise the deadline state machine without a fixture script.
    if budget.exhausted:
        return expired_before_launch()
    # Candidate Blender code receives only runtime/display variables. In
    # particular, provider credentials and unrelated host secrets are not
    # inherited by the modeling process. The optional bubblewrap wrapper adds
    # a kernel-enforced network/filesystem boundary when available; its status
    # is preserved in the trusted execution record.
    allowed_environment = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "DISPLAY",
        "XDG_RUNTIME_DIR", "TMPDIR", "TEMP", "TMP",
        "LIBGL_ALWAYS_SOFTWARE", "EGL_PLATFORM",
        "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS",
    }
    environment = {
        key: value for key, value in os.environ.items() if key in allowed_environment
    }
    if extra_env:
        environment.update(extra_env)
    sandbox_status = "declared_only"
    resource_limits: dict[str, int | None] = {
        "cpu_seconds": max(1, int(timeout) + 1),
        "file_bytes": 512 * 1024 * 1024,
        "address_space_bytes": None,
    }
    limits = dict(_DEFAULT_WORKSPACE_LIMITS if workspace_limits is None else workspace_limits)
    if (
        set(limits) != set(_DEFAULT_WORKSPACE_LIMITS)
        or any(type(value) is not int or value <= 0 for value in limits.values())
    ):
        raise ValueError("workspace_limits must contain positive integer quota fields")
    resource_limits.update({f"workspace_{key}": value for key, value in limits.items()})
    context["sandbox_io"] = {"status": "not_started", "pid": None}
    try:
        runner_path = Path(command[command.index("--python") + 1])
        context["sandbox_io"] = prepare_blender_sandbox(
            blender_binary, runner_path, working_directory, deadline=budget.deadline,
        )
    except (InspectionFailure, OSError, ValueError, IndexError) as error:
        context["sandbox_io"] = getattr(error, "parent_io", context["sandbox_io"])
        if budget.exhausted:
            return expired_before_launch()
        return Execution("unavailable", EXECUTOR_UNAVAILABLE, None,
                         time.monotonic() - started, "", str(error), "preparation_failed", resource_limits)
    except BaseException as error:
        context["sandbox_io"] = getattr(error, "parent_io", context["sandbox_io"])
        raise
    prefix = context["sandbox_io"]["result"]["prefix"]
    if prefix:
        command = [*prefix, *command]
        sandbox_status = "enforced"
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "cwd": working_directory,
        "env": environment,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True

        def set_limits() -> None:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (resource_limits["cpu_seconds"], resource_limits["cpu_seconds"]),
            )
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (resource_limits["file_bytes"], resource_limits["file_bytes"]),
            )

        kwargs["preexec_fn"] = set_limits
    if budget.exhausted:
        return expired_before_launch()
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as error:
        return Execution(
            "unavailable",
            EXECUTOR_UNAVAILABLE,
            None,
            time.monotonic() - started,
            "",
            str(error),
            sandbox_status,
            resource_limits,
        )
    guard = None
    guard_receipt: dict[str, object] | None = None
    guard_started = time.monotonic()
    if _WORKSPACE_GUARD.is_file() and hasattr(process, "pid"):
        guard_command = [
            sys.executable,
            "-I",
            str(_WORKSPACE_GUARD),
            "--root",
            str(working_directory),
            "--target-pid",
            str(process.pid),
            "--deadline",
            str(budget.deadline),
            "--max-bytes",
            str(limits["max_bytes"]),
            "--max-files",
            str(limits["max_files"]),
            "--max-depth",
            str(limits["max_depth"]),
            "--max-file-bytes",
            str(limits["max_file_bytes"]),
        ]
        try:
            guard = subprocess.Popen(
                guard_command,
                cwd=working_directory,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
                start_new_session=True,
            )
        except OSError as error:
            guard_receipt = {
                "protocol": "l1-workspace-guard-v1",
                "status": "guard_failed",
                "error_type": type(error).__name__,
                "reason": str(error),
            }
    elif not hasattr(process, "pid"):
        # Lightweight unit-test doubles do not expose a process group. They
        # cannot provide a host cleanup receipt, but must not be interpreted
        # as a production guard failure or make the candidate look failed.
        guard_receipt = {
            "protocol": "l1-workspace-guard-v1",
            "status": "test_double",
        }
    stdout, stderr = "", ""
    communication_failure: tuple[str, str, int | None, str, str] | None = None
    try:
        stdout, stderr = communicate_bounded(
            process, timeout=budget.remaining, max_pipe_bytes=16 * 1024 * 1024
        )
    except subprocess.TimeoutExpired as error:
        _kill_tree(process)
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        communication_failure = (
            "timeout", EXECUTOR_TIMEOUT, None, stdout, stderr
        )
    except PipeEncodingError as error:
        _kill_tree(process)
        communication_failure = (
            "protocol_error", EXECUTOR_PROTOCOL_ERROR, process.returncode,
            error.stdout, error.stderr,
        )
    except PipeLimitError as error:
        _kill_tree(process)
        communication_failure = (
            "protocol_error", EXECUTOR_PROTOCOL_ERROR, process.returncode,
            error.stdout, error.stderr,
        )
    except OSError as error:
        _kill_tree(process)
        communication_failure = (
            "process_error", EXECUTOR_PROCESS_ERROR, process.returncode,
            stdout, str(error),
        )
    finally:
        _kill_tree(process)
    if guard is not None:
        # Cleanup is bounded post-execution evidence work and must remain
        # available even when candidate execution consumed the shared budget.
        guard_receipt = _finish_workspace_guard(
            guard, deadline=time.monotonic() + _GUARD_CLEANUP_SECONDS
        )
    if guard_receipt is None:
        guard_receipt = {
            "protocol": "l1-workspace-guard-v1",
            "status": "not_started",
        }
    guard_receipt.setdefault("elapsed_seconds", max(0.0, time.monotonic() - guard_started))
    cleanup = guard_receipt.get("process_cleanup")
    if isinstance(cleanup, dict) and cleanup.get("cleanup_ack") is False:
        return Execution(
            "resource_error",
            "EXECUTOR_WORKSPACE_CLEANUP_FAILED",
            process.returncode,
            time.monotonic() - started,
            stdout,
            stderr,
            sandbox_status,
            resource_limits,
            _rng_trace(stdout),
            guard_receipt,
        )
    if guard_receipt.get("status") == "quota_exceeded":
        return Execution(
            "resource_exhausted",
            "EXECUTOR_WORKSPACE_QUOTA",
            process.returncode,
            time.monotonic() - started,
            stdout,
            stderr,
            sandbox_status,
            resource_limits,
            _rng_trace(stdout),
            guard_receipt,
        )
    if communication_failure is not None:
        status, error_code, return_code, stdout, stderr = communication_failure
        return Execution(
            status,
            error_code,
            return_code,
            time.monotonic() - started,
            stdout,
            stderr,
            sandbox_status,
            resource_limits,
            _rng_trace(stdout),
            guard_receipt,
        )
    if guard_receipt.get("status") == "deadline_exhausted" or budget.exhausted:
        return Execution(
            "budget_exhausted",
            "EXECUTOR_BUDGET_EXHAUSTED",
            process.returncode,
            time.monotonic() - started,
            stdout,
            stderr,
            sandbox_status,
            resource_limits,
            _rng_trace(stdout),
            guard_receipt,
        )
    if guard_receipt.get("status") in {"guard_failed", "not_started"}:
        return Execution(
            "resource_error",
            "EXECUTOR_WORKSPACE_GUARD_FAILED",
            process.returncode,
            time.monotonic() - started,
            stdout,
            stderr,
            sandbox_status,
            resource_limits,
            _rng_trace(stdout),
            guard_receipt,
        )
    status = "success" if process.returncode == 0 and output.is_file() else "process_error"
    return Execution(
        status,
        None if status == "success" else EXECUTOR_PROCESS_ERROR,
        process.returncode,
        time.monotonic() - started,
        stdout,
        stderr,
        sandbox_status,
        resource_limits,
        _rng_trace(stdout),
        guard_receipt,
    )
