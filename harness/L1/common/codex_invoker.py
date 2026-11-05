"""One Codex CLI attempt with process-tree timeout handling."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from src.evaluator.l1_budget import DeadlineBudget
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_parent_io import resolve_executable, write_bounded_json
from src.evaluator.l1_response_io import ResponseReadError, read_response
from src.generator.client import (
    GeneratorConfig,
    build_generation_command as build_codex_command,
)

from .bundle import BUNDLE_SCHEMA, MAX_RESPONSE_BYTES, decode_response
from .errors import (
    GENERATOR_EMPTY_OUTPUT,
    GENERATOR_PROCESS_ERROR,
    GENERATOR_PROTOCOL_ERROR,
    GENERATOR_TIMEOUT,
)
from .process_io import MAX_PIPE_BYTES as BOUNDED_PIPE_BYTES
from .process_io import PipeEncodingError, PipeLimitError, communicate_bounded
from .processes import stop_process_group as _kill_tree

MAX_PROMPT_BYTES = 8 * 1024 * 1024
MAX_PIPE_BYTES = BOUNDED_PIPE_BYTES
_WORKSPACE_GUARD = Path(__file__).resolve().parents[3] / "src" / "evaluator" / "l1_workspace_guard.py"
_GUARD_RECEIPT_LIMIT = 4096
_GUARD_CLEANUP_SECONDS = 2.0
DEFAULT_WORKSPACE_LIMITS: dict[str, int] = {
    "max_bytes": 512 * 1024 * 1024,
    "max_files": 4096,
    "max_depth": 32,
    "max_file_bytes": 256 * 1024 * 1024,
}


def _validate_paths(workspace: Path, output_path: Path) -> str | None:
    try:
        workspace_info = workspace.lstat()
    except OSError as error:
        return f"workspace unavailable: {type(error).__name__}"
    if workspace.is_symlink() or not stat.S_ISDIR(workspace_info.st_mode):
        return "workspace must be a regular directory"
    parent = output_path.parent
    try:
        parent_info = parent.lstat()
        output_info = output_path.lstat() if output_path.exists() or output_path.is_symlink() else None
    except OSError as error:
        return f"output path unavailable: {type(error).__name__}"
    if parent.is_symlink() or not stat.S_ISDIR(parent_info.st_mode):
        return "output parent must be a regular directory"
    if output_info is not None and (output_path.is_symlink() or not stat.S_ISREG(output_info.st_mode)):
        return "output path must be a regular non-symlink file or absent"
    return None


def _canonical_runtime_launcher(
    config: GeneratorConfig, command: list[str], *, deadline: float
) -> tuple[list[str], dict]:
    """Resolve the selected Codex/Docker launcher to an executable file.

    The command builder intentionally leaves the first element equal to the
    configured launcher.  Auditing that element here keeps both local Codex
    and Docker runtimes on the same boundary: a missing, non-regular, or
    non-executable launcher becomes a stable process error before any child is
    spawned.  Test/adaptor commands that deliberately replace the first
    element retain the existing seam and are not mistaken for production
    launcher evidence.
    """
    requested = (
        config.codex_binary if config.runtime == "local" else config.docker_binary
    )
    if not command or command[0] != requested:
        # Explicit test/adaptor command seams may replace the launcher. The
        # production command builder leaves command[0] equal to the declared
        # runtime binary, so only that path takes the canonical audit below.
        return command, {"status": "adapter_command", "requested": requested, "pid": None}
    receipt = resolve_executable(requested, deadline=deadline)
    command = list(command)
    command[0] = receipt["result"]["path"]
    return command, receipt


def _decode_pipe(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _communicate_bounded(process: subprocess.Popen, prompt: str, timeout: float) -> tuple[str, str]:
    """Send one bounded UTF-8 prompt and collect bounded process streams.

    A small duck-typed fallback keeps unit-test process doubles compatible;
    real ``Popen`` objects use nonblocking descriptors and never accumulate
    more than ``MAX_PIPE_BYTES`` per stream in the parent.
    """
    payload = prompt.encode("utf-8")
    if len(payload) > MAX_PROMPT_BYTES:
        raise ValueError("Codex prompt exceeds bounded input size")
    return communicate_bounded(
        process,
        timeout=timeout,
        input_bytes=payload,
        max_input_bytes=MAX_PROMPT_BYTES,
        max_pipe_bytes=MAX_PIPE_BYTES,
    )


def _guard_limits(value: dict[str, int] | None) -> dict[str, int] | None:
    if value is None:
        return None
    if (
        set(value) != set(DEFAULT_WORKSPACE_LIMITS)
        or any(type(item) is not int or item <= 0 for item in value.values())
    ):
        raise ValueError("workspace_limits must contain positive integer quota fields")
    return dict(value)


def _start_workspace_guard(
    workspace: Path,
    target_pid: int,
    deadline: float,
    limits: dict[str, int] | None,
    environment: dict[str, str],
) -> subprocess.Popen | None:
    if limits is None:
        return None
    if not _WORKSPACE_GUARD.is_file():
        raise OSError("L1 workspace guard is unavailable")
    command = [
        sys.executable,
        "-I",
        str(_WORKSPACE_GUARD),
        "--root",
        str(workspace),
        "--target-pid",
        str(target_pid),
        "--deadline",
        str(deadline),
        "--max-bytes",
        str(limits["max_bytes"]),
        "--max-files",
        str(limits["max_files"]),
        "--max-depth",
        str(limits["max_depth"]),
        "--max-file-bytes",
        str(limits["max_file_bytes"]),
    ]
    return subprocess.Popen(
        command,
        cwd=workspace,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
    )


def _finish_workspace_guard(
    guard: subprocess.Popen | None, *, deadline: float
) -> dict[str, object] | None:
    if guard is None:
        return None
    captured = b""
    error: BaseException | None = None
    try:
        remaining = min(2.0, max(0.0, deadline - time.monotonic()))
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


@dataclass(frozen=True)
class Invocation:
    status: str
    error_code: str | None
    return_code: int | None
    elapsed_seconds: float
    stdout: str
    stderr: str
    output: str | None
    bundle: dict | None = None
    output_io: dict | None = None
    resource_limits: dict[str, int] | None = None
    workspace_guard: dict[str, object] | None = None
    launcher_io: dict | None = None


def run_once(
    config: GeneratorConfig,
    prompt: str,
    workspace: Path,
    output_path: Path,
    timeout: float,
    image_paths: Sequence[Path] = (),
    *,
    deadline: float | None = None,
    delivery_format: str = "python",
    workspace_limits: dict[str, int] | None = None,
) -> Invocation:
    context: dict = {}
    try:
        result = _run_once(
            config, prompt, workspace, output_path, timeout, image_paths,
            deadline=deadline, delivery_format=delivery_format,
            workspace_limits=workspace_limits, context=context,
        )
    except BaseException as error:
        error.launcher_io = context.get("launcher_io")
        raise
    return replace(result, launcher_io=context.get("launcher_io"))


def _run_once(
    config: GeneratorConfig,
    prompt: str,
    workspace: Path,
    output_path: Path,
    timeout: float,
    image_paths: Sequence[Path],
    *,
    deadline: float | None,
    delivery_format: str,
    workspace_limits: dict[str, int] | None,
    context: dict,
) -> Invocation:
    budget = DeadlineBudget.start(timeout, deadline=deadline)
    started = budget.started

    def expired_before_launch() -> Invocation:
        shared = deadline is not None and time.monotonic() >= deadline
        return Invocation(
            "budget_exhausted" if shared else "timeout",
            "GENERATOR_BUDGET_EXHAUSTED" if shared else GENERATOR_TIMEOUT,
            None, time.monotonic() - started, "", "", None,
        )

    if budget.exhausted:
        return expired_before_launch()
    workspace_limits = _guard_limits(workspace_limits)
    path_error = _validate_paths(workspace, output_path)
    if path_error is not None:
        return Invocation(
            "protocol_error", GENERATOR_PROTOCOL_ERROR, None,
            time.monotonic() - started, "", path_error, None,
        )
    if delivery_format not in {"python", "bundle"}:
        raise ValueError("Unknown L1 delivery format")
    schema = None
    if delivery_format == "bundle":
        schema = output_path.parent / "submission-output.schema.json"
        write_bounded_json(schema, BUNDLE_SCHEMA, deadline=budget.deadline)
    command = build_codex_command(
        config,
        output_path=output_path,
        working_directory=workspace,
        image_paths=image_paths,
        sandbox_mode="read-only",
        output_schema=schema,
    )
    if budget.exhausted:
        return expired_before_launch()
    context["launcher_io"] = {"status": "not_started", "pid": None}
    try:
        command, context["launcher_io"] = _canonical_runtime_launcher(
            config, command, deadline=budget.deadline,
        )
    except (InspectionFailure, OSError, ValueError) as error:
        context["launcher_io"] = getattr(error, "parent_io", context["launcher_io"])
        if budget.exhausted:
            return expired_before_launch()
        label = "Codex" if config.runtime == "local" else "Docker"
        return Invocation(
            "process_error", GENERATOR_PROCESS_ERROR, None,
            time.monotonic() - started, "", f"{label} launcher unavailable: {error}", None,
        )
    except BaseException as error:
        context["launcher_io"] = getattr(error, "parent_io", context["launcher_io"])
        raise
    allowed_environment = {
        "PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP",
        # Test doubles use this switch; it is never a production credential.
        "FAKE_CODEX_MODE",
    }
    environment = {
        key: value for key, value in os.environ.items() if key in allowed_environment
    }
    environment["CODEX_API_KEY"] = config.api_key
    kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": False,
        "cwd": workspace,
        "env": environment,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    if budget.exhausted:
        return expired_before_launch()
    try:
        process = subprocess.Popen(command, **kwargs)
    except (OSError, ValueError) as error:
        return Invocation(
            "process_error", GENERATOR_PROCESS_ERROR, None,
            time.monotonic() - started, "", str(error), None,
        )
    guard: subprocess.Popen | None = None
    guard_receipt: dict[str, object] | None = None
    try:
        if workspace_limits is not None:
            guard = _start_workspace_guard(
                workspace, process.pid, budget.deadline, workspace_limits, environment
            )
    except OSError as error:
        _kill_tree(process)
        return Invocation(
            "resource_error", "GENERATOR_WORKSPACE_GUARD_FAILED", None,
            time.monotonic() - started, "", str(error), None,
            None, None, workspace_limits,
        )
    stdout, stderr = "", ""
    communication_failure: tuple[str, str, int | None, str, str] | None = None
    try:
        stdout, stderr = _communicate_bounded(process, prompt, budget.remaining)
    except subprocess.TimeoutExpired as error:
        _kill_tree(process)
        communication_failure = (
            "timeout", GENERATOR_TIMEOUT, None,
            _decode_pipe(error.stdout), _decode_pipe(error.stderr),
        )
    except OSError as error:
        communication_failure = (
            "process_error", GENERATOR_PROCESS_ERROR, process.returncode,
            stdout, str(error),
        )
    except (UnicodeError, ValueError, PipeEncodingError, PipeLimitError) as error:
        communication_failure = (
            "protocol_error", GENERATOR_PROTOCOL_ERROR, None,
            "", str(error),
        )
    finally:
        _kill_tree(process)
        # Candidate execution may have consumed the shared deadline.  Guard
        # cleanup is evidence/recovery work, not new candidate work; grant it
        # one bounded grace interval so detached descendants can be reaped and
        # the receipt can report a cleanup ACK instead of a false guard failure.
        guard_receipt = _finish_workspace_guard(
            guard, deadline=time.monotonic() + _GUARD_CLEANUP_SECONDS
        )
    cleanup = guard_receipt.get("process_cleanup") if guard_receipt else None
    if isinstance(cleanup, dict) and cleanup.get("cleanup_ack") is False:
        return Invocation(
            "resource_error", "GENERATOR_WORKSPACE_CLEANUP_FAILED", process.returncode,
            time.monotonic() - started, stdout, stderr, None, None, None,
            workspace_limits, guard_receipt,
        )
    if guard_receipt is not None and guard_receipt.get("status") == "quota_exceeded":
        return Invocation(
            "resource_exhausted", "GENERATOR_WORKSPACE_QUOTA", process.returncode,
            time.monotonic() - started, stdout, stderr, None, None, None,
            workspace_limits, guard_receipt,
        )
    if communication_failure is not None:
        status, code, return_code, stdout, stderr = communication_failure
        return Invocation(
            status, code, return_code, time.monotonic() - started,
            stdout, stderr, None, None, None, workspace_limits, guard_receipt,
        )
    if guard_receipt is not None and guard_receipt.get("status") in {
        "guard_failed", "not_started"
    }:
        return Invocation(
            "resource_error", "GENERATOR_WORKSPACE_GUARD_FAILED", process.returncode,
            time.monotonic() - started, stdout, stderr, None, None, None,
            workspace_limits, guard_receipt,
        )
    elapsed = time.monotonic() - started

    def attach(value: Invocation) -> Invocation:
        return replace(
            value,
            resource_limits=workspace_limits,
            workspace_guard=guard_receipt,
        )
    if budget.exhausted:
        return attach(Invocation("timeout", GENERATOR_TIMEOUT, process.returncode,
                                 elapsed, stdout, stderr, None))
    if process.returncode != 0:
        return attach(Invocation(
            "process_error",
            GENERATOR_PROCESS_ERROR,
            process.returncode,
            elapsed,
            stdout,
            stderr,
            None,
        ))
    if not output_path.is_file() or output_path.stat().st_size == 0:
        return attach(Invocation(
            "empty_output",
            GENERATOR_EMPTY_OUTPUT,
            process.returncode,
            elapsed,
            stdout,
            stderr,
            None,
        ))
    output_io = None
    try:
        if output_path.is_symlink() or output_path.stat().st_size > MAX_RESPONSE_BYTES:
            raise ValueError("Invalid or oversized L1 model response file")
        if hasattr(process, "pid"):
            raw_bytes, output_io = read_response(
                output_path,
                deadline=budget.deadline,
                limit=MAX_RESPONSE_BYTES,
            )
        else:
            # Test doubles that only implement ``communicate`` cannot expose
            # a worker PID/receipt. Production Popen objects always take the
            # bounded response-reader branch above.
            raw_bytes = output_path.read_bytes()
            output_io = {
                "protocol": "l1-response-reader-execution-v1",
                "status": "test_double",
                "path": str(output_path),
                "bytes": len(raw_bytes),
            }
        raw = raw_bytes.decode("utf-8")
        if not raw.strip():
            return attach(Invocation("empty_output", GENERATOR_EMPTY_OUTPUT, process.returncode,
                                     elapsed, stdout, stderr, None, None, output_io))
        output, bundle = decode_response(raw)
    except ResponseReadError as error:
        if error.code == "GENERATOR_BUDGET_EXHAUSTED":
            return attach(Invocation(
                "budget_exhausted",
                "GENERATOR_BUDGET_EXHAUSTED",
                process.returncode,
                time.monotonic() - started,
                stdout,
                stderr,
                None,
                None,
                error.receipt,
            ))
        return attach(Invocation(
            "protocol_error",
            GENERATOR_PROTOCOL_ERROR,
            process.returncode,
            elapsed,
            stdout,
            stderr,
            str(error),
            None,
            error.receipt,
        ))
    except UnicodeDecodeError as error:
        return attach(Invocation(
            "protocol_error",
            GENERATOR_PROTOCOL_ERROR,
            process.returncode,
            elapsed,
            stdout,
            stderr,
            str(error),
            None,
            output_io,
        ))
    except (TypeError, ValueError, RuntimeError) as error:
        return attach(Invocation(
            "protocol_error",
            GENERATOR_PROTOCOL_ERROR,
            process.returncode,
            elapsed,
            stdout,
            stderr,
            str(error),
            None,
            output_io,
        ))
    if budget.exhausted:
        return attach(Invocation("timeout", GENERATOR_TIMEOUT, process.returncode,
                                 time.monotonic() - started, stdout, stderr, None))
    return attach(Invocation(
        "success", None, process.returncode, elapsed, stdout, stderr, output, bundle, output_io
    ))
