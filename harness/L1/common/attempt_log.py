"""JSON-safe attempt and artifact recording helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from src.evaluator.l1_persistence import JsonPersistence

_PERSISTENCE: ContextVar[JsonPersistence | None] = ContextVar(
    "l1_harness_json_persistence", default=None
)


@contextmanager
def persistence_scope(session: JsonPersistence):
    """Route harness JSON writes through one deadline/cleanup session.

    The context is deliberately opt-in so legacy unit-test callbacks can still
    replace ``write_json_atomic(path, value)`` and observe phase boundaries.
    Production L1 pipeline stages enter it around their own writes.
    """
    token = _PERSISTENCE.set(session)
    try:
        yield session
    finally:
        _PERSISTENCE.reset(token)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def failure_cleanup_evidence(session: JsonPersistence) -> dict[str, Any]:
    """Summarize one non-renewable failure-cleanup allowance.

    The summary is deliberately small and contains no exception text or
    candidate payload. Unknown model/tool/cost values remain ``None`` instead
    of being inferred from files or directory existence.
    """
    evidence = session.evidence()
    rows = [row for row in evidence.get("records", []) if isinstance(row, dict)]
    cleanup_rows = [row for row in rows if row.get("scope") == "failure_cleanup"]
    process_groups = []
    for row in cleanup_rows:
        execution = row.get("execution")
        if not isinstance(execution, dict):
            continue
        process_groups.append({
            "pid": execution.get("pid"),
            "process_group": execution.get("process_group"),
            "status": execution.get("status"),
            "leader_reaped": execution.get("leader_reaped"),
            "group_kill_sent": execution.get("group_kill_sent"),
        })
    if not cleanup_rows:
        status = "not_started"
    elif all(row.get("status") == "completed" for row in cleanup_rows):
        status = "completed"
    else:
        status = "incomplete"
    return {
        "protocol": "l1-failure-cleanup-v1",
        "status": status,
        "scope": "persistence_writers_only",
        "observation": "snapshot_before_enclosing_write_not_a_commit_ack",
        "candidate_process_tree_status": "not_audited",
        "evaluation_deadline_monotonic": evidence.get("deadline_monotonic"),
        "cleanup_deadline_monotonic": evidence.get("cleanup_deadline_monotonic"),
        "cleanup_records": len(cleanup_rows),
        "cleanup_records_completed": sum(
            row.get("status") == "completed" for row in cleanup_rows
        ),
        "process_groups": process_groups,
        "costs": {
            "protocol": "l1-cost-v1",
            "status": "unknown",
            "wall_seconds": None,
            "model_calls": None,
            "total_tokens": None,
            "tool_calls": None,
        },
    }


def write_json(path: Path, value: Any) -> None:
    session = _PERSISTENCE.get()
    if session is not None:
        session.write(path, value)
        return
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def write_json_atomic(path: Path, value: Any) -> None:
    """Checkpoint without exposing a truncated manifest to readers/crashes."""
    session = _PERSISTENCE.get()
    if session is not None:
        session.write(path, value)
        return
    content = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
