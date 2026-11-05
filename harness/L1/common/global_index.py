"""Append-only trusted index shards for L1 generation and rerun records."""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_parent_io import ensure_directory
from src.evaluator.l1_persistence import (
    CLEANUP_SECONDS,
    MAX_JSON_BYTES,
    REAP_RESERVE_SECONDS,
    JsonPersistence,
)
from src.evaluator.l1_persistence_receipt import validate_persistence_receipt
from src.evaluator.l1_result import read_result

PROTOCOL = "l1-global-record-index-v1"


def latest_write_receipt(path: Path, persistence: JsonPersistence, *,
                         digest: str | None = None, commit_mode: str | None = None) -> dict:
    """Use the LAST attempted write, never resurrect an earlier successful ACK.

    The session belongs to the trusted caller. Structural validation alone is
    not authenticity or a filesystem isolation guarantee.
    """
    row = next((item for item in reversed(persistence.records)
                if isinstance(item, dict) and item.get("path") == str(path)), None)
    if row is None:
        raise ValueError("global index requires an acknowledged target write")
    return validate_persistence_receipt(
        row, path=path, digest=digest, evaluation_deadline=persistence.deadline,
        cleanup_deadline=persistence.cleanup_deadline,
        commit_mode=commit_mode or row.get("commit_mode"),
    )


def _acknowledged(path: Path, ack: Any, *, persistence: JsonPersistence,
                  commit_mode: str = "create_only") -> dict[str, Any]:
    latest = latest_write_receipt(path, persistence, commit_mode=commit_mode)
    if ack != latest:
        raise ValueError("global index receipt does not match last session write")
    return latest


def _validate_local_index(payload: dict[str, Any], *, persistence: JsonPersistence,
                          deadline: float, cleanup_deadline: float,
                          evidence: dict) -> tuple[dict, dict]:
    """Require the global shard to point at an ACKed local record index."""
    path = payload.get("record_index")
    digest = payload.get("record_index_sha256")
    if (not isinstance(path, str) or not path or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
        raise ValueError("global index requires local record index binding")
    local = Path(path)
    ack = latest_write_receipt(local, persistence, digest=digest)
    evidence["local_index_receipt"] = ack
    if "record_index_receipt" in payload and payload["record_index_receipt"] != ack:
        raise ValueError("global index local ACK does not match last session write")
    value, reception = read_result(local, deadline=deadline, max_bytes=MAX_JSON_BYTES,
                                   cleanup_deadline=cleanup_deadline)
    evidence["local_index_read"] = reception
    if reception["result_sha256"] != digest:
        raise ValueError("global index local record index hash mismatch")
    if reception["bytes_received"] != ack["bytes"] or not isinstance(value, dict):
        raise ValueError("global index local record index bytes/object mismatch")
    return ack, reception


def publish_global_index(
    output_dir: Path,
    run_id: str,
    payload: dict[str, Any],
    *,
    deadline: float,
    persistence: JsonPersistence,
    cleanup: bool = False,
) -> dict[str, Any]:
    """Publish one immutable run shard after its local index is ACKed."""
    evidence = {"protocol": "l1-global-publication-v1", "run_id": run_id,
                "status": "not_started"}
    try:
        result = _publish_global_index(output_dir, run_id, payload, deadline=deadline,
                                       persistence=persistence, cleanup=cleanup, evidence=evidence)
    except BaseException as error:
        evidence["status"] = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
        for attribute, label in (("result_reception", "local_index_read"),
                                 ("parent_io", "directory_io"), ("json_persistence", "receipt")):
            receipt = getattr(error, attribute, None)
            if receipt is not None:
                evidence[label] = receipt
        error.global_index_publication = evidence
        raise
    evidence["status"] = "completed"
    return {**result, "publication_evidence": evidence}


def _publish_global_index(output_dir, run_id, payload, *, deadline, persistence,
                           cleanup, evidence):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", run_id):
        raise ValueError("global index requires a safe run identifier")
    if (type(deadline) not in (int, float) or not math.isfinite(deadline)
            or deadline != persistence.deadline or type(cleanup) is not bool):
        raise ValueError("global index requires the owning persistence deadline/scope")
    if not cleanup and persistence.cleanup_deadline is not None:
        raise InspectionFailure("infrastructure_error", "PERSISTENCE_AFTER_CLEANUP",
                                "Normal publication cannot resume after cleanup")
    end = persistence.begin_cleanup() if cleanup else deadline + CLEANUP_SECONDS
    io_deadline = end - REAP_RESERVE_SECONDS if cleanup else deadline
    evidence.update(deadline_monotonic=io_deadline, cleanup_deadline_monotonic=end,
                    evaluation_deadline_monotonic=deadline,
                    scope="failure_cleanup" if cleanup else "evaluation")
    if time.monotonic() >= io_deadline:
        raise InspectionFailure(
            "infrastructure_error",
            "PERSISTENCE_CLEANUP_EXHAUSTED" if cleanup else "EVALUATION_BUDGET_EXHAUSTED",
            "No global publication I/O after shared deadline",
        )
    local_ack, local_read = _validate_local_index(
        payload, persistence=persistence, deadline=io_deadline, cleanup_deadline=end,
        evidence=evidence,
    )
    index_dir = output_dir / "harness_records" / "index"
    directory = ensure_directory(index_dir, deadline=io_deadline, parents=True,
                                  cleanup_deadline=end)
    evidence["directory_io"] = directory["execution"]
    path = index_dir / f"{run_id}.json"
    value = {
        "protocol": PROTOCOL,
        "run_id": run_id,
        "record_index": payload,
        # Precommit proof only: the actual global ACK is returned afterwards.
        "local_index_receipt": local_ack,
        "local_index_read": local_read,
    }
    try:
        written = persistence.write(path, value, cleanup=cleanup, replace=False)
    except InspectionFailure as error:
        execution = (getattr(error, "json_persistence", None) or {}).get("execution") or {}
        if (execution.get("writer_result") or {}).get("error_type") == "FileExistsError":
            # Collision authority is the actual atomic create-only worker,
            # never a racy and potentially blocking parent exists()/stat().
            collision = FileExistsError(f"global record index already exists: {path}")
            collision.json_persistence = error.json_persistence
            raise collision from error
        raise
    evidence["receipt"] = written
    ack = _acknowledged(path, written, persistence=persistence)
    evidence["receipt"] = ack
    return {
        "protocol": PROTOCOL,
        "path": str(path),
        "sha256": ack["sha256"],
        "receipt": ack,
        "local_index_receipt": local_ack,
        "local_index_read": local_read,
        "directory_io": directory["execution"],
        "persistence": persistence.evidence(),
    }


__all__ = ["PROTOCOL", "latest_write_receipt", "publish_global_index"]
