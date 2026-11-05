"""Exec-based request persistence with nonblocking, bounded JSON streaming."""

from __future__ import annotations

import hashlib
import json
import math
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

from .l1_budget import BudgetExhausted
from .l1_failures import InspectionFailure
from .l1_json_stream import json_chunks

WRITER = Path(__file__).with_name("l1_request_writer.py")
CLEANUP_SECONDS = 2.0
RECEIPT_LIMIT = 4096
RECEIPT_PROTOCOL = "l1-request-writer-v1"


def _clock() -> float:
    monotonic = time.monotonic()
    performance = time.perf_counter()
    return performance if abs(monotonic - performance) > 100_000 else monotonic


def _effective_deadline(deadline: float) -> float:
    """Map a synthetic parent deadline to the worker's real monotonic clock."""
    monotonic = time.monotonic()
    performance = time.perf_counter()
    if abs(monotonic - performance) > 100_000 and deadline < performance - 1_000:
        return deadline + (performance - monotonic)
    return deadline


def _command(path, deadline, limit):
    return [
        sys.executable,
        "-I",
        str(WRITER),
        "--target",
        str(path),
        "--deadline",
        str(deadline),
        "--limit",
        str(limit),
    ]


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate request receipt key")
        value[key] = item
    return value


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _receipts(captured, execution, started, deadline):
    # Check byte size before decoding; only tiny trusted protocol messages
    # cross back into the parent, never the serialized request itself.
    if len(captured) > RECEIPT_LIMIT:
        raise ValueError("Invalid request receipt size")
    messages = [
        json.loads(row, object_pairs_hook=_object) for row in captured.splitlines()
    ]
    if len(messages) > 2:
        raise ValueError("Too many request receipts")
    for row in messages:
        if (
            type(row) is not dict
            or row.get("protocol") != RECEIPT_PROTOCOL
            or type(row.get("pid")) is not int
            or row["pid"] != execution["pid"]
            or type(row.get("process_group")) is not int
            or row["process_group"] != execution["pid"]
        ):
            raise ValueError("Unbound request writer receipt")
    if messages:
        first = messages[0]
        entered = first.get("entered_monotonic")
        if (
            first.get("phase") != "started"
            or not _finite(entered)
            or not started <= entered <= deadline
        ):
            raise ValueError("Unbound request writer start")
        execution["writer_started"] = first
    if len(messages) == 2:
        last = messages[1]
        completed = last.get("completed_monotonic")
        if (
            last.get("phase") != "finished"
            or last.get("status") not in ("completed", "failed")
            or not _finite(completed)
            or not messages[0]["entered_monotonic"]
            <= completed
            <= execution["finished_monotonic"]
        ):
            raise ValueError("Unbound request writer completion")
        if last["status"] == "completed" and (
            completed > deadline
            or type(last.get("bytes")) is not int
            or not 0 < last["bytes"] == execution["bytes_sent"]
            or last.get("sha256") != execution["sent_sha256"]
        ):
            raise ValueError(
                "Request receipt does not match the transmitted bytes/deadline"
            )
        execution["writer_result"] = last
    return messages


def prepare_request(
    path: Path,
    value: dict,
    *,
    deadline: float,
    max_bytes: int,
    replace: bool = False,
    cleanup_deadline: float | None = None,
) -> dict:
    if not _finite(deadline) or type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Finite deadline and positive byte limit required")
    if type(replace) is not bool:
        raise ValueError("Explicit boolean replacement policy required")
    if cleanup_deadline is not None and (
        not _finite(cleanup_deadline) or cleanup_deadline < deadline
    ):
        raise ValueError(
            "Cleanup deadline must be finite and no earlier than work deadline"
        )
    worker_deadline = _effective_deadline(float(deadline))
    worker_cleanup_deadline = (
        _effective_deadline(float(cleanup_deadline))
        if cleanup_deadline is not None
        else None
    )
    started = _clock()
    execution = {
        "protocol": "l1-request-preparation-v1",
        "status": "not_started",
        "pid": None,
        "started_monotonic": started,
        "deadline_monotonic": deadline,
        "worker_deadline_monotonic": worker_deadline,
        "cleanup_limit_seconds": CLEANUP_SECONDS,
        "encoding": "native_json_bounded_step_cooperative",
        "persistence": "exec_process_hard_deadline",
        "request_path": str(path),
        "request_sha256": None,
        "bytes": None,
        "commit_mode": "replace_regular" if replace else "create_only",
        "cleanup_deadline_monotonic": cleanup_deadline,
        "worker_cleanup_deadline_monotonic": worker_cleanup_deadline,
    }
    process, captured, failure = None, bytearray(), None
    sent_digest, sent_bytes = hashlib.sha256(), 0
    try:
        if started >= worker_deadline:
            raise BudgetExhausted("No request preparation after shared deadline")
        environment = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
        }
        command = _command(path, worker_deadline, max_bytes)
        if replace:
            command.append("--replace-regular")
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
        )
        execution.update(status="preparing", pid=process.pid, process_group=process.pid)
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        for chunk in json_chunks(value, deadline=worker_deadline, max_bytes=max_bytes):
            pending = memoryview(chunk)
            while pending:
                remaining = worker_deadline - _clock()
                if remaining <= 0:
                    raise BudgetExhausted("Request write exceeded shared deadline")
                _, writable, _ = select.select([], [process.stdin], [], remaining)
                if not writable:
                    raise BudgetExhausted(
                        "Blocked request write exhausted shared deadline"
                    )
                try:
                    written = os.write(process.stdin.fileno(), pending)
                    if written <= 0:
                        raise OSError("Request pipe made no progress")
                    sent_digest.update(pending[:written])
                    sent_bytes += written
                    pending = pending[written:]
                except BlockingIOError:
                    continue
        process.stdin.close()
        try:
            process.wait(timeout=max(0.0, worker_deadline - _clock()))
        except subprocess.TimeoutExpired as error:
            raise BudgetExhausted(
                "Request persistence exceeded shared deadline"
            ) from error
        if _clock() >= worker_deadline:
            raise BudgetExhausted("Late request receipt rejected")
    except (
        OSError,
        ValueError,
        TypeError,
        RuntimeError,
        OverflowError,
        KeyboardInterrupt,
        SystemExit,
    ) as error:
        failure = error
    finally:
        cleanup_started = _clock()
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as error:
                execution["cleanup_error"] = type(error).__name__
                if failure is None:
                    failure = error
            execution["group_kill_sent"] = True
            try:
                remaining = (
                    CLEANUP_SECONDS
                    if cleanup_deadline is None
                    else min(
                        CLEANUP_SECONDS, max(0.0, worker_cleanup_deadline - _clock())
                    )
                )
                process.wait(timeout=remaining)
                execution["leader_reaped"] = True
            except subprocess.TimeoutExpired:
                execution["leader_reaped"] = False
                if failure is None:
                    failure = RuntimeError("Request writer could not be reaped")
            execution["return_code"] = process.returncode
            try:
                # Bounded receipt only. There is never candidate JSON here.
                os.set_blocking(process.stdout.fileno(), False)
                while len(captured) <= RECEIPT_LIMIT:
                    piece = os.read(
                        process.stdout.fileno(), RECEIPT_LIMIT + 1 - len(captured)
                    )
                    if not piece:
                        break
                    captured.extend(piece)
            except BlockingIOError:
                pass
            except OSError as error:
                if failure is None:
                    failure = error
            process.stdin.close()
            process.stdout.close()
        execution.update(
            bytes_sent=sent_bytes,
            sent_sha256=sent_digest.hexdigest(),
            finished_monotonic=_clock(),
            elapsed_seconds=_clock() - started,
            cleanup_seconds=_clock() - cleanup_started,
        )
    try:
        messages = _receipts(captured, execution, started, worker_deadline)
        if failure is None and (
            len(messages) != 2
            or messages[-1].get("status") != "completed"
            or execution.get("return_code") != 0
            or not execution.get("leader_reaped")
        ):
            raise ValueError("Request persistence did not complete")
        if failure is None:
            expected_commit = "replace_regular" if replace else "create_only"
            if (
                messages[-1].get("commit_mode") != expected_commit
                or messages[-1].get("directory_synced") is not True
            ):
                raise ValueError(
                    "Commit mode and directory synchronization receipt required"
                )
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        if failure is None:
            failure = error
    if failure is None and _clock() >= worker_deadline:
        failure = BudgetExhausted(
            "Request receipt finalization exceeded shared deadline"
        )
    if failure is not None:
        interrupted = isinstance(failure, (KeyboardInterrupt, SystemExit))
        exhausted = isinstance(failure, BudgetExhausted)
        execution["status"] = (
            "interrupted"
            if interrupted
            else "budget_exhausted"
            if exhausted
            else "failed"
        )
        if interrupted:
            failure.request_preparation = execution
            raise failure
        code = (
            "EVALUATION_BUDGET_EXHAUSTED"
            if exhausted
            else "COMPUTE_INPUT_LIMIT"
            if isinstance(failure, OverflowError)
            else "COMPUTE_REQUEST_PREPARATION_FAILED"
        )
        error = InspectionFailure("infrastructure_error", code, type(failure).__name__)
        error.request_preparation = execution
        raise error from failure
    result = messages[-1]
    execution.update(
        status="completed", bytes=result["bytes"], request_sha256=result["sha256"]
    )
    return execution
