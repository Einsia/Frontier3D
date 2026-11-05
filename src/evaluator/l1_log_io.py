"""Supervision for the bounded evaluator log sink."""

from __future__ import annotations

import hashlib
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path
from subprocess import Popen as _Popen

from .l1_budget import BudgetExhausted
from .l1_failures import InspectionFailure

WORKER = Path(__file__).with_name("l1_log_writer.py")
CLEANUP_SECONDS = 2.0
RECEIPT_LIMIT = 4096
MAX_LOG_BYTES = 16 * 1024 * 1024
PROTOCOL = "l1-log-writer-v1"


class LogSink:
    """Start before a target process and finish after its stdout pipe closes."""

    def __init__(self, target: Path, deadline: float, *, limit: int = MAX_LOG_BYTES,
                 scope: str = "evaluation"):
        if type(limit) is not int or limit <= 0:
            raise ValueError("positive log limit required")
        if scope not in {"evaluation", "failure_cleanup", "file"}:
            raise ValueError("unknown bounded writer scope")
        self.target, self.deadline, self.limit = Path(target), deadline, limit
        self.scope = scope
        self.process = None
        self.execution = {
            "protocol": "l1-file-writer-execution-v1" if scope == "file" else "l1-log-writer-execution-v1",
            "path": str(self.target), "scope": scope,
            "status": "not_started", "pid": None, "deadline_monotonic": deadline,
            "limit": limit, "cleanup_limit_seconds": CLEANUP_SECONDS,
        }

    def start(self):
        if time.monotonic() >= self.deadline:
            raise InspectionFailure(
                "infrastructure_error",
                "FILE_IO_BUDGET_EXHAUSTED" if self.scope == "file" else "LOG_IO_BUDGET_EXHAUSTED",
                "No bounded writer after deadline",
            )
        environment = {k: v for k, v in os.environ.items()
                       if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}}
        self.process = _Popen(
            [sys.executable, "-I", str(WORKER), "--target", str(self.target),
             "--deadline", str(self.deadline), "--limit", str(self.limit),
             "--scope", self.scope],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            env=environment, start_new_session=True,
        )
        self.execution.update(status="running", pid=self.process.pid, process_group=self.process.pid,
                               started_monotonic=time.monotonic())
        return self.process.stdin

    def _kill(self):
        if self.process is None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.execution["group_kill_sent"] = True
        except ProcessLookupError:
            self.execution["group_kill_sent"] = True
        except OSError as error:
            self.execution.update(group_kill_sent=False, cleanup_error=type(error).__name__)
        try:
            self.process.wait(timeout=CLEANUP_SECONDS)
            self.execution["leader_reaped"] = True
        except subprocess.TimeoutExpired:
            self.execution["leader_reaped"] = False
        self.execution["return_code"] = self.process.returncode

    def finish(self, *, cleanup: bool = False) -> dict:
        if self.process is None:
            return self.execution
        failure: BaseException | None = None
        captured = bytearray()
        try:
            deadline = self.deadline if not cleanup else self.deadline + CLEANUP_SECONDS
            if self.process.poll() is None:
                self.process.wait(timeout=max(0.0, deadline - time.monotonic()))
            # stderr is a bounded receipt channel. Do not use communicate(),
            # whose implicit wait is unbounded under a hostile descendant.
            fd = self.process.stderr.fileno()
            os.set_blocking(fd, False)
            while len(captured) <= RECEIPT_LIMIT:
                ready, _, _ = select.select([fd], [], [], 0)
                if not ready:
                    break
                chunk = os.read(fd, RECEIPT_LIMIT + 1 - len(captured))
                if not chunk:
                    break
                captured.extend(chunk)
        except (OSError, subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit) as error:
            failure = error
        if failure is not None or self.process.poll() is None:
            self._kill()
        else:
            self.execution.update(return_code=self.process.returncode,
                                  leader_reaped=True, group_kill_sent=True)
        self.execution["finished_monotonic"] = time.monotonic()
        self.execution["elapsed_seconds"] = self.execution["finished_monotonic"] - self.execution["started_monotonic"]
        if len(captured) > RECEIPT_LIMIT:
            failure = failure or ValueError("oversized log receipt")
        rows = []
        try:
            rows = [json.loads(line) for line in bytes(captured).splitlines()]
            if len(rows) > 2 or any(row.get("protocol") != PROTOCOL or row.get("pid") != self.process.pid
                                    or row.get("process_group") != self.process.pid for row in rows):
                raise ValueError("unbound log receipt")
            if rows:
                self.execution["worker_started"] = rows[0]
            if len(rows) == 2:
                self.execution["worker_result"] = rows[1]
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            failure = failure or error
        if failure is None and (len(rows) != 2 or rows[-1].get("status") != "completed"
                                or self.process.returncode != 0 or not self.execution.get("leader_reaped")):
            failure = ValueError("log writer did not complete")
        if failure is None and not cleanup and time.monotonic() >= self.deadline:
            failure = BudgetExhausted("late log receipt rejected")
        self.execution["status"] = "completed" if failure is None else (
            "budget_exhausted" if isinstance(failure, (BudgetExhausted, subprocess.TimeoutExpired)) else "failed"
        )
        if failure is not None:
            self.execution["failure_code"] = (
                ("FILE_IO_BUDGET_EXHAUSTED" if self.scope == "file" else "LOG_IO_BUDGET_EXHAUSTED")
                if isinstance(failure, (BudgetExhausted, subprocess.TimeoutExpired))
                else ("FILE_IO_FAILED" if self.scope == "file" else "LOG_IO_FAILED")
            )
            self.execution["failure_type"] = type(failure).__name__
            # Log persistence is evidence, not a reason to replace the
            # primary worker failure. Callers decide whether an otherwise
            # successful target may be downgraded for this infrastructure
            # error.
        return self.execution


def write_bounded_log(
    target: Path,
    value: str | bytes,
    *,
    deadline: float,
    limit: int = MAX_LOG_BYTES,
) -> dict:
    """Publish one Harness log through a bounded writer process.

    The caller receives a receipt even when the log cannot be committed. A
    failed log is evidence of infrastructure trouble, not a replacement for
    the candidate/worker status that produced the log.
    """
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        raise TypeError("log value must be text or bytes")
    sink = LogSink(target, deadline, limit=limit)
    stream = None
    failure: BaseException | None = None
    try:
        stream = sink.start()
        if len(payload) > limit:
            raise ValueError("log byte limit exceeded")
        os.set_blocking(stream.fileno(), False)
        pending = memoryview(payload)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExhausted("Log write exhausted shared deadline")
            _, writable, _ = select.select([], [stream], [], min(0.05, remaining))
            if not writable:
                continue
            try:
                written = os.write(stream.fileno(), pending)
            except BlockingIOError:
                continue
            if written <= 0:
                raise OSError("Log pipe made no progress")
            pending = pending[written:]
    except (
        OSError,
        ValueError,
        TypeError,
        BudgetExhausted,
        InspectionFailure,
        KeyboardInterrupt,
        SystemExit,
    ) as error:
        failure = error
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    if failure is not None:
        sink._kill()
    receipt = sink.finish(cleanup=failure is not None)
    if failure is not None:
        receipt.update(
            status="budget_exhausted"
            if isinstance(failure, BudgetExhausted)
            or getattr(failure, "code", None) == "LOG_IO_BUDGET_EXHAUSTED"
            else "failed",
            failure_code=(
                "LOG_IO_BUDGET_EXHAUSTED"
                if isinstance(failure, BudgetExhausted)
                or getattr(failure, "code", None) == "LOG_IO_BUDGET_EXHAUSTED"
                else "LOG_IO_FAILED"
            ),
            failure_type=type(failure).__name__,
        )
    return receipt


def write_bounded_file(
    target: Path,
    value: str | bytes,
    *,
    deadline: float,
    limit: int = 64 * 1024 * 1024,
    replace: bool = False,
) -> dict:
    """Write one new Harness-owned file through the bounded sink.

    ``replace`` is retained in the API for explicit policy checking; the
    current worker intentionally refuses every existing target so a late
    writer cannot overwrite an earlier candidate or record.
    """
    if replace:
        raise ValueError("bounded file writer currently supports create-only commits")
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        raise TypeError("file value must be text or bytes")
    if type(limit) is not int or limit <= 0:
        raise ValueError("positive file limit required")
    if len(payload) > limit:
        return {
            "protocol": "l1-file-writer-execution-v1",
            "scope": "file",
            "path": str(target),
            "status": "failed",
            "pid": None,
            "deadline_monotonic": deadline,
            "limit": limit,
            "failure_code": "FILE_IO_FAILED",
            "failure_type": "ValueError",
            "reason": "file byte limit exceeded",
        }
    if time.monotonic() >= deadline:
        return {
            "protocol": "l1-file-writer-execution-v1",
            "scope": "file",
            "path": str(target),
            "status": "budget_exhausted",
            "pid": None,
            "deadline_monotonic": deadline,
            "limit": limit,
            "failure_code": "FILE_IO_BUDGET_EXHAUSTED",
            "failure_type": "BudgetExhausted",
        }
    sink = LogSink(target, deadline, limit=limit, scope="file")
    stream = None
    failure: BaseException | None = None
    digest = hashlib.sha256(payload).hexdigest()
    try:
        stream = sink.start()
        os.set_blocking(stream.fileno(), False)
        pending = memoryview(payload)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExhausted("File write exhausted shared deadline")
            _, writable, _ = select.select([], [stream], [], min(0.05, remaining))
            if not writable:
                continue
            try:
                written = os.write(stream.fileno(), pending)
            except BlockingIOError:
                continue
            if written <= 0:
                raise OSError("File pipe made no progress")
            pending = pending[written:]
        stream.close()
        stream = None
    except (OSError, ValueError, BudgetExhausted, InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        failure = error
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    if failure is not None:
        sink._kill()
    receipt = sink.finish(cleanup=failure is not None)
    if failure is not None:
        receipt.update(
            status="budget_exhausted" if isinstance(failure, BudgetExhausted)
            or getattr(failure, "code", None) == "FILE_IO_BUDGET_EXHAUSTED" else "failed",
            failure_code="FILE_IO_BUDGET_EXHAUSTED" if isinstance(failure, BudgetExhausted)
            or getattr(failure, "code", None) == "FILE_IO_BUDGET_EXHAUSTED" else "FILE_IO_FAILED",
            failure_type=type(failure).__name__,
        )
    result = receipt.get("worker_result", {})
    if receipt.get("status") == "completed" and (
        result.get("bytes") != len(payload) or result.get("sha256") != digest
    ):
        receipt.update(status="failed", failure_code="FILE_IO_FAILED", failure_type="ValueError")
    return receipt
