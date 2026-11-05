"""Append-only failure records; never rewrite a previously published run."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from src.evaluator.l1_compute_receipt import compute_binding
from src.evaluator.l1_persistence import JsonPersistence

from .attempt_log import failure_cleanup_evidence
from .global_index import _acknowledged, publish_global_index


def publish_failure_records(context: dict[str, Any], error: BaseException, *, stage: str) -> dict:
    """Publish a separate failure event using one shared cleanup allowance.

    Paths/hashes in the index come only from ACKed writes. A collision, missing
    ACK or cleanup error cannot attach an existing file as the current result.
    The returned receipt must itself be retained by a trusted caller.
    """
    if stage not in {"generation", "rerun"}:
        raise ValueError("unsupported failure stage")
    session = context.get("persistence")
    run_dir, trusted = context.get("run_dir"), context.get("trusted_record")
    if not isinstance(session, JsonPersistence) or not isinstance(run_dir, Path):
        return {}
    compute = getattr(error, "compute_execution", None)
    finalized = getattr(error, "finalization_report", None)
    if not isinstance(finalized, dict):
        finalized = context.get("finalization_report")
    if isinstance(finalized, dict) and isinstance(finalized.get("compute_execution"), dict):
        compute = finalized["compute_execution"]
    if isinstance(compute, dict):
        compute_cleanup = compute.get("record_persistence", {}).get("cleanup_deadline_monotonic")
        if isinstance(compute_cleanup, (float, int)):
            session.cleanup_deadline = min(session.begin_cleanup(), compute_cleanup)
    session.begin_cleanup()
    failure_id = f"failure-{uuid.uuid4().hex}"
    status = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
    local = run_dir / f"{failure_id}.json"
    trusted_failure = trusted.with_name(f"{failure_id}.json") if isinstance(trusted, Path) else None
    index_path = run_dir / f"{failure_id}.index.json"
    receipts: dict[str, dict] = {}
    errors: list[str] = []
    record = {
        "schema_version": 1,
        "protocol": f"l1-{stage}-failure-v1",
        "task_id": context.get("task_id"),
        "run_id": context.get("run_id"),
        "failure_id": failure_id,
        "final_status": status,
        "generation_passed": False,
        "evaluation_completed": False,
        "provenance_status": "unverified",
        "not_measurable": True,
        "failure": {
            "exception_type": type(error).__name__,
            "code": getattr(error, "code", f"{stage.upper()}_STAGE_ERROR"),
        },
        "prior_records": {
            "local_record": str(run_dir / "harness_record.json"),
            "trusted_record": str(trusted) if isinstance(trusted, Path) else None,
            "policy": "historical_only_not_failure_authority",
        },
        "path_io": [context[key] for key in ("output_path_io", "run_path_io", "trusted_path_io")
                    if context.get(key) is not None],
    }
    for key in ("resource_invalidation", "superseded_report", "launcher_discovery"):
        if context.get(key) is not None:
            record[key] = context[key]
    if isinstance(compute, dict):
        record["compute_execution"] = compute
    if isinstance(getattr(error, "launcher_io", None), dict):
        record["launcher_io"] = error.launcher_io
    if isinstance(getattr(error, "sandbox_io", None), dict):
        record["sandbox_io"] = error.sandbox_io
    for key in ("inspector_execution", "inspector_persistence", "reproduction_inspections"):
        if isinstance(getattr(error, key, None), dict):
            record[key] = getattr(error, key)
    if isinstance(finalized, dict):
        # Carry the ACK, not candidate-sized report/geometry payloads. A later
        # consumer must reopen the acknowledged report; this is not a pass.
        record["evaluation_finalization"] = finalized.get("finalization")
        record["evaluation_report_path"] = finalized.get("report_path")
        record["scoring_failure"] = finalized.get("scoring_failure")

    def write(label, path, value):
        if not isinstance(path, Path):
            return
        try:
            receipts[label] = _acknowledged(
                path, session.write(path, value, cleanup=True, replace=False), persistence=session,
            )
        except BaseException as failure:  # noqa: BLE001 -- preserve initiating error/interruption
            errors.append(f"{label}:{type(failure).__name__}")

    # These are immutable events. The later index/returned receipt contains
    # ACKs for both copies; no evidence-refresh write can clobber an old run.
    for label, path in (("local_record", local), ("trusted_record", trusted_failure)):
        record["cleanup"] = failure_cleanup_evidence(session)
        record["costs"] = record["cleanup"]["costs"]
        record["record_persistence"] = session.evidence()
        record["failure_publication_errors"] = list(errors)
        write(label, path, record)

    indexed = {
        "protocol": "l1-harness-record-index-v1",
        "task_id": context.get("task_id"),
        "run_id": context.get("run_id"),
        "failure_id": failure_id,
        "final_status": status,
        "provenance_status": "unverified",
        "resource_integrity_passed": False if stage == "rerun" else None,
        "not_measurable": True,
        "resource_invalidation": context.get("resource_invalidation"),
        "record_receipts": dict(receipts),
        "cleanup": failure_cleanup_evidence(session),
        "failure_publication_errors": list(errors),
    }
    indexed["costs"] = indexed["cleanup"]["costs"]
    if isinstance(compute, dict):
        indexed["compute_execution"] = compute_binding(compute)
    if isinstance(finalized, dict):
        indexed["evaluation_finalization"] = finalized.get("finalization")
        indexed["evaluation_report_path"] = finalized.get("report_path")
    for label in ("local_record", "trusted_record"):
        ack = receipts.get(label, {})
        indexed[label] = ack.get("path")
        indexed[f"{label}_sha256"] = ack.get("sha256")
    write("record_index", index_path, indexed)

    global_receipt = None
    global_failure = None
    output = context.get("output_dir")
    # Do not publish an index of an unacknowledged index (even if a writer
    # linked a file but failed before fsync/ACK).
    if isinstance(output, Path) and "record_index" in receipts:
        try:
            ack = receipts["record_index"]
            global_receipt = publish_global_index(
                output, failure_id,
                {**indexed, "record_index": ack["path"], "record_index_sha256": ack["sha256"],
                 "record_index_receipt": ack, "event_kind": "failure",
                 "supersedes_run_id": context.get("run_id"),
                 "cleanup": failure_cleanup_evidence(session)},
                deadline=session.deadline, persistence=session, cleanup=True,
            )
        except BaseException as failure:  # noqa: BLE001 -- preserve initiating error/interruption
            global_failure = getattr(failure, "global_index_publication", None)
            errors.append(f"global_index:{type(failure).__name__}")

    return {
        "run_dir": str(run_dir), "final_status": status, "failure_id": failure_id,
        "harness_record": receipts.get("trusted_record", {}).get("path"),
        "run_harness_record": receipts.get("local_record", {}).get("path"),
        "record_index": receipts.get("record_index", {}).get("path"),
        "global_index": global_receipt, "publication_receipts": receipts,
        "global_index_failure": global_failure,
        "launcher_io": getattr(error, "launcher_io", None),
        "sandbox_io": getattr(error, "sandbox_io", None),
        "inspector_execution": getattr(error, "inspector_execution", None),
        "inspector_persistence": getattr(error, "inspector_persistence", None),
        "reproduction_inspections": getattr(error, "reproduction_inspections", None),
        "launcher_discovery": context.get("launcher_discovery"),
        "failure_publication_errors": errors,
        "cleanup": failure_cleanup_evidence(session),
    }
