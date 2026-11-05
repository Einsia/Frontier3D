"""Exec-based result reads with cooperative incremental JSON parsing."""

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
from .l1_json_parse import JSONStreamParser
from .l1_json_stream import CHUNK_BYTES

READER = Path(__file__).with_name("l1_result_reader.py")
CLEANUP_SECONDS = 2.0
RECEIPT_LIMIT = 4096


def _command(path, deadline, limit):
    return [
        sys.executable,
        "-I",
        str(READER),
        "--source",
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
            raise ValueError("Duplicate reader receipt key")
        value[key] = item
    return value


def _nonfinite(value):
    raise ValueError("Nonfinite reader receipt")


def _time(value):
    return type(value) in (int, float) and math.isfinite(value)


def _receipts(data, execution):
    if len(data) > RECEIPT_LIMIT:
        raise ValueError("Oversized reader receipts")
    messages = [
        json.loads(row, object_pairs_hook=_object, parse_constant=_nonfinite)
        for row in data.splitlines()
    ]
    if len(messages) > 2:
        raise ValueError("Too many reader receipts")
    for row in messages:
        if (
            type(row) is not dict
            or row.get("protocol") != "l1-result-reader-v1"
            or type(row.get("pid")) is not int
            or row["pid"] != execution["pid"]
            or type(row.get("process_group")) is not int
            or row["process_group"] != execution["pid"]
        ):
            raise ValueError("Unbound reader receipt")
    if messages:
        first = messages[0]
        entered = first.get("entered_monotonic")
        if (
            set(first)
            != {"protocol", "phase", "pid", "process_group", "entered_monotonic"}
            or first["phase"] != "started"
            or not _time(entered)
            or not execution["started_monotonic"]
            <= entered
            <= execution["finished_monotonic"]
        ):
            raise ValueError("Invalid reader start")
        execution["reader_started"] = first
    if len(messages) == 2:
        last = messages[1]
        completed = last.get("completed_monotonic")
        if (
            last.get("phase") != "finished"
            or last.get("status") not in ("completed", "failed")
            or not _time(completed)
            or not first["entered_monotonic"]
            <= completed
            <= execution["finished_monotonic"]
        ):
            raise ValueError("Invalid reader completion")
        if last["status"] == "completed":
            expected = {
                "protocol",
                "phase",
                "status",
                "pid",
                "process_group",
                "completed_monotonic",
                "bytes",
                "sha256",
                "source_stat",
            }
            metadata = last.get("source_stat")
            if (
                set(last) != expected
                or type(metadata) is not dict
                or set(metadata) != {"device", "inode", "bytes", "mtime_ns", "ctime_ns"}
                or not all(type(v) is int for v in metadata.values())
                or type(last.get("bytes")) is not int
                or not 0
                < last["bytes"]
                == execution["bytes_received"]
                == metadata["bytes"]
                or last.get("sha256") != execution["received_sha256"]
                or completed > execution["deadline_monotonic"]
            ):
                raise ValueError("Reader completion is not bound to received bytes")
        execution["reader_result"] = last
    return messages


def read_result(path: Path, *, deadline: float, max_bytes: int,
                cleanup_deadline: float | None = None):
    if cleanup_deadline is not None and (
        not _time(cleanup_deadline) or not _time(deadline)
        or not deadline <= cleanup_deadline <= deadline + CLEANUP_SECONDS
    ):
        raise ValueError("Result reader cleanup must share a bounded caller allowance")
    parser = JSONStreamParser(deadline=deadline, max_bytes=max_bytes)
    started = time.monotonic()
    execution = {
        "protocol": "l1-result-reception-v1",
        "status": "not_started",
        "pid": None,
        "started_monotonic": started,
        "deadline_monotonic": deadline,
        "cleanup_limit_seconds": CLEANUP_SECONDS,
        "cleanup_deadline_monotonic": cleanup_deadline,
        "source_path": str(path),
        "reading": "exec_process_hard_deadline",
        "decoding": "incremental_json_cooperative",
    }
    process, failure, result = None, None, None
    digest, count, receipts = hashlib.sha256(), 0, bytearray()
    try:
        parser.check()
        environment = {
            k: v
            for k, v in os.environ.items()
            if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT"}
        }
        process = subprocess.Popen(
            _command(path, deadline, max_bytes),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        execution.update(status="reading", pid=process.pid, process_group=process.pid)
        streams = {process.stdout.fileno(), process.stderr.fileno()}
        for fd in streams:
            os.set_blocking(fd, False)
        while streams:
            parser.check()
            if process.poll() is not None and not execution.get(
                "descendant_cleanup_after_exit"
            ):
                # A child may inherit a pipe after its leader has exited.
                # End the trusted group before waiting for EOF, but still
                # consume/validate every byte already in the pipes.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                execution["descendant_cleanup_after_exit"] = True
            ready, _, _ = select.select(
                list(streams), [], [], min(0.05, max(0.0, deadline - time.monotonic()))
            )
            if not ready:
                continue
            for fd in ready:
                chunk = os.read(
                    fd,
                    CHUNK_BYTES
                    if fd == process.stdout.fileno()
                    else RECEIPT_LIMIT + 1 - len(receipts),
                )
                if not chunk:
                    streams.remove(fd)
                elif fd == process.stdout.fileno():
                    count += len(chunk)
                    digest.update(chunk)
                    parser.feed(chunk)
                else:
                    receipts.extend(chunk)
                    if len(receipts) > RECEIPT_LIMIT:
                        raise ValueError("Oversized result reader receipts")
        try:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise BudgetExhausted(
                "Result reader exit exhausted shared deadline"
            ) from error
        result = parser.finish()
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
        cleanup_started = time.monotonic()
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
                execution["group_kill_sent"] = True
            except ProcessLookupError:
                execution["group_kill_sent"] = True
            except OSError as error:
                execution["group_kill_sent"] = False
                if failure is None:
                    failure = error
            try:
                process.wait(timeout=(CLEANUP_SECONDS if cleanup_deadline is None else
                                      max(0.0, cleanup_deadline - time.monotonic())))
                execution["leader_reaped"] = True
            except subprocess.TimeoutExpired:
                execution["leader_reaped"] = False
                if failure is None:
                    failure = RuntimeError("Result reader could not be reaped")
            execution["return_code"] = process.returncode
            # Preserve already-written bounded receipts even after parse
            # failure; never drain unbounded result bytes during cleanup.
            try:
                os.set_blocking(process.stderr.fileno(), False)
                while len(receipts) <= RECEIPT_LIMIT:
                    chunk = os.read(
                        process.stderr.fileno(), RECEIPT_LIMIT + 1 - len(receipts)
                    )
                    if not chunk:
                        break
                    receipts.extend(chunk)
            except (BlockingIOError, OSError):
                pass
            process.stdout.close()
            process.stderr.close()
        execution.update(
            bytes_received=count,
            received_sha256=digest.hexdigest(),
            finished_monotonic=time.monotonic(),
            elapsed_seconds=time.monotonic() - started,
            cleanup_seconds=time.monotonic() - cleanup_started,
        )
    try:
        messages = _receipts(receipts, execution)
        if failure is None and (
            len(messages) != 2
            or messages[-1]["status"] != "completed"
            or execution.get("return_code") != 0
            or not execution.get("leader_reaped")
        ):
            raise ValueError("Result reader did not complete")
    except (ValueError, TypeError, RecursionError, OverflowError) as error:
        if failure is None:
            failure = error
    if failure is None and time.monotonic() >= deadline:
        failure = BudgetExhausted("Result finalization exceeded shared deadline")
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
            failure.result_reception = execution
            raise failure
        error = InspectionFailure(
            "infrastructure_error",
            "EVALUATION_BUDGET_EXHAUSTED" if exhausted else "COMPUTE_PROTOCOL_ERROR",
            type(failure).__name__,
        )
        error.result_reception = execution
        raise error from failure
    execution.update(status="completed", result_sha256=digest.hexdigest())
    return result, execution
