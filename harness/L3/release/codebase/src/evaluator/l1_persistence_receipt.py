"""Validate already trusted L1 persistence ACKs without touching the filesystem.

This verifies consistency, not authenticity. Callers still authenticate the
enclosing record and independently reload the exact bytes under a deadline.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .l1_persistence import CLEANUP_SECONDS, MAX_JSON_BYTES, REAP_RESERVE_SECONDS


def _require(condition, message):
    if not condition:
        raise ValueError(f"Persistence ACK: {message}")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_persistence_receipt(
    row, *, path, evaluation_deadline, cleanup_deadline=None,
    scope=None, digest=None, size=None, commit_mode="replace_regular",
):
    """Require the completed parent ACK and both actual child receipts.

    ``cleanup_deadline`` is the session's single failure allowance, not the
    normal write's reap limit. Historical deadlines are compared to each
    other, never to the current clock of a later report-reload operation.
    """
    _require(isinstance(row, dict), "missing row")
    _require(_finite(evaluation_deadline), "invalid evaluation deadline")
    if cleanup_deadline is not None:
        _require(_finite(cleanup_deadline)
                 and cleanup_deadline <= evaluation_deadline + CLEANUP_SECONDS,
                 "cleanup deadline renewed")
    _require(row.get("protocol") == "l1-json-persistence-v1"
             and row.get("status") == "completed", "incomplete row")
    _require(isinstance(row.get("path"), str) and row["path"] == str(path), "wrong path")
    _require(isinstance(row.get("sha256"), str)
             and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None, "invalid hash")
    _require(type(row.get("bytes")) is int and 0 < row["bytes"] <= MAX_JSON_BYTES, "invalid size")
    _require(digest is None or row["sha256"] == digest, "hash mismatch")
    _require(size is None or row["bytes"] == size, "size mismatch")
    actual_scope = row.get("scope")
    _require(scope is None or actual_scope == scope, "wrong scope")
    if actual_scope == "evaluation":
        deadline, end = evaluation_deadline, evaluation_deadline + CLEANUP_SECONDS
    else:
        _require(actual_scope == "failure_cleanup" and cleanup_deadline is not None, "missing cleanup scope")
        deadline, end = cleanup_deadline - REAP_RESERVE_SECONDS, cleanup_deadline
    _require(row.get("evaluation_deadline_monotonic") == evaluation_deadline
             and row.get("deadline_monotonic") == deadline
             and row.get("cleanup_deadline_monotonic") == end, "row deadline mismatch")
    execution = row.get("execution")
    _require(isinstance(execution, dict), "missing execution")
    _require(execution.get("protocol") == "l1-request-preparation-v1"
             and execution.get("status") == "completed", "writer incomplete")
    pid = execution.get("pid")
    _require(type(pid) is int and pid > 0 and execution.get("process_group") == pid, "writer identity mismatch")
    _require(execution.get("leader_reaped") is True and execution.get("group_kill_sent") is True
             and type(execution.get("return_code")) is int and execution["return_code"] == 0,
             "writer cleanup incomplete")
    _require(execution.get("request_path") == str(path)
             and execution.get("request_sha256") == execution.get("sent_sha256") == row["sha256"]
             and type(execution.get("bytes")) is int and type(execution.get("bytes_sent")) is int
             and execution["bytes"] == execution["bytes_sent"] == row["bytes"], "writer byte binding mismatch")
    _require(execution.get("deadline_monotonic") == execution.get("worker_deadline_monotonic") == deadline
             and execution.get("cleanup_deadline_monotonic") == execution.get("worker_cleanup_deadline_monotonic") == end,
             "writer deadline mismatch")
    start, finish = execution.get("writer_started"), execution.get("writer_result")
    _require(isinstance(start, dict) and isinstance(finish, dict), "missing child receipts")
    _require(all(item.get("protocol") == "l1-request-writer-v1"
                 and type(item.get("pid")) is int and item["pid"] == pid
                 and type(item.get("process_group")) is int and item["process_group"] == pid
                 for item in (start, finish)), "child identity mismatch")
    _require(start.get("phase") == "started" and finish.get("phase") == "finished"
             and finish.get("status") == "completed", "child did not finish")
    _require(finish.get("sha256") == row["sha256"] and type(finish.get("bytes")) is int
             and finish["bytes"] == row["bytes"], "child byte binding mismatch")
    _require(commit_mode in {"replace_regular", "create_only"}
             and row.get("commit_mode") == execution.get("commit_mode") == finish.get("commit_mode") == commit_mode
             and finish.get("directory_synced") is True, "durable commit missing")
    times = [execution.get("started_monotonic"), start.get("entered_monotonic"),
             finish.get("completed_monotonic"), execution.get("finished_monotonic"), deadline]
    _require(all(_finite(value) for value in times) and times == sorted(times), "late or unordered receipt")
    _require(Path(row["path"]).name != "", "empty filename")
    return row


def validate_persistence_session(session, *, evaluation_deadline):
    _require(isinstance(session, dict)
             and session.get("protocol") == "l1-json-persistence-session-v1", "missing session")
    _require(_finite(evaluation_deadline) and session.get("deadline_monotonic") == evaluation_deadline,
             "session deadline mismatch")
    cleanup = session.get("cleanup_deadline_monotonic")
    _require(cleanup is None or (_finite(cleanup) and cleanup <= evaluation_deadline + CLEANUP_SECONDS),
             "session cleanup deadline renewed")
    _require(session.get("cleanup_seconds") == CLEANUP_SECONDS
             and session.get("reap_reserve_seconds") == REAP_RESERVE_SECONDS, "session cleanup policy mismatch")
    _require(isinstance(session.get("records"), list), "session records missing")
    return session["records"], cleanup
