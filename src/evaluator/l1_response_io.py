"""Deadline-bound reading of a model response file."""

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

from .l1_budget import BudgetExhausted

WORKER = Path(__file__).with_name("l1_response_reader.py")
CLEANUP_SECONDS = 2.0
RECEIPT_LIMIT = 4096
PROTOCOL = "l1-response-reader-v1"


class ResponseReadError(ValueError):
    def __init__(self, code: str, message: str, *, receipt: dict | None = None):
        super().__init__(message)
        self.code = code
        self.receipt = receipt


def _kill(process: subprocess.Popen, execution: dict) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
        execution["group_kill_sent"] = True
    except ProcessLookupError:
        execution["group_kill_sent"] = True
    except OSError as error:
        execution.update(group_kill_sent=False, cleanup_error=type(error).__name__)
    try:
        process.wait(timeout=CLEANUP_SECONDS)
        execution["leader_reaped"] = True
    except subprocess.TimeoutExpired:
        execution["leader_reaped"] = False
    execution["return_code"] = process.returncode


def read_response(path: Path, *, deadline: float, limit: int) -> tuple[bytes, dict]:
    """Read a regular response through a killable process and verify its receipt."""
    if type(limit) is not int or limit <= 0:
        raise ValueError("positive response limit required")
    started = time.monotonic()
    execution = {
        "protocol": "l1-response-reader-execution-v1",
        "path": str(path),
        "status": "not_started",
        "pid": None,
        "deadline_monotonic": deadline,
        "limit": limit,
        "cleanup_limit_seconds": CLEANUP_SECONDS,
    }
    if started >= deadline:
        execution["status"] = "budget_exhausted"
        execution["failure_code"] = "GENERATOR_BUDGET_EXHAUSTED"
        raise ResponseReadError("GENERATOR_BUDGET_EXHAUSTED", "No response reader after deadline", receipt=execution)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    process = None
    stdout = bytearray()
    stderr = bytearray()
    failure: BaseException | None = None
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(WORKER),
                "--target",
                str(path),
                "--deadline",
                str(deadline),
                "--limit",
                str(limit),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        execution.update(status="running", pid=process.pid, process_group=process.pid)
        streams = {process.stdout.fileno(), process.stderr.fileno()}
        for fd in streams:
            os.set_blocking(fd, False)
        while streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BudgetExhausted("Response read exhausted shared deadline")
            ready, _, _ = select.select(list(streams), [], [], min(0.05, remaining))
            if not ready:
                continue
            for fd in ready:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    streams.remove(fd)
                elif fd == process.stdout.fileno():
                    stdout.extend(chunk)
                    if len(stdout) > limit:
                        raise ValueError("response byte limit exceeded")
                else:
                    stderr.extend(chunk)
                    if len(stderr) > RECEIPT_LIMIT:
                        raise ValueError("oversized response receipt")
        process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except (OSError, ValueError, subprocess.TimeoutExpired, BudgetExhausted, KeyboardInterrupt, SystemExit) as error:
        failure = error
    finally:
        if process is not None:
            if failure is not None or process.poll() is None:
                _kill(process, execution)
            else:
                execution.update(return_code=process.returncode, leader_reaped=True, group_kill_sent=True)
            execution["finished_monotonic"] = time.monotonic()
            execution["elapsed_seconds"] = execution["finished_monotonic"] - started
            process.stdout.close()
            process.stderr.close()
    rows: list[dict] = []
    try:
        rows = [json.loads(line) for line in bytes(stderr).splitlines()]
        if len(rows) > 2 or any(
            not isinstance(row, dict)
            or row.get("protocol") != PROTOCOL
            or row.get("pid") != execution.get("pid")
            or row.get("process_group") != execution.get("pid")
            for row in rows
        ):
            raise ValueError("unbound response reader receipt")
        if rows:
            entered = rows[0].get("entered_monotonic")
            if rows[0].get("phase") != "started" or not isinstance(entered, (int, float)) or not started <= entered <= deadline:
                raise ValueError("invalid response reader start receipt")
            execution["worker_started"] = rows[0]
        if len(rows) == 2:
            execution["worker_result"] = rows[1]
            completed = rows[1].get("completed_monotonic")
            if (
                rows[1].get("phase") != "finished"
                or rows[1].get("status") not in {"completed", "failed"}
                or not isinstance(completed, (int, float))
                or completed > execution["finished_monotonic"]
            ):
                raise ValueError("invalid response reader completion receipt")
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        failure = failure or error
    if failure is None and (
        len(rows) != 2
        or rows[-1].get("status") != "completed"
        or execution.get("return_code") != 0
        or not execution.get("leader_reaped")
    ):
        failure = ValueError("response reader did not complete")
    if failure is None and time.monotonic() >= deadline:
        failure = BudgetExhausted("late response receipt rejected")
    if failure is None:
        result = rows[-1]
        digest = hashlib.sha256(stdout).hexdigest()
        if result.get("bytes") != len(stdout) or result.get("sha256") != digest:
            failure = ValueError("response reader hash/length mismatch")
        elif not stdout:
            failure = ValueError("empty response")
    if failure is not None:
        execution["status"] = "budget_exhausted" if isinstance(failure, (BudgetExhausted, subprocess.TimeoutExpired)) else "failed"
        execution["failure_code"] = "GENERATOR_BUDGET_EXHAUSTED" if isinstance(failure, (BudgetExhausted, subprocess.TimeoutExpired)) else "GENERATOR_RESPONSE_READ_FAILED"
        execution["failure_type"] = type(failure).__name__
        raise ResponseReadError(execution["failure_code"], str(failure), receipt=execution) from failure
    execution["status"] = "completed"
    return bytes(stdout), execution


__all__ = ["ResponseReadError", "read_response"]
