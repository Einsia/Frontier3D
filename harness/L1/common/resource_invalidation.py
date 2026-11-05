"""Publish resource invalidation as a new L1 report, preserving old bytes.

No recomputation, old-ACK relabeling or in-place overwrite. The predecessor is
historical evidence, not authority for the new unavailable result. All new
writes and the caller's later indices share one nonrenewable cleanup budget.
"""

from __future__ import annotations

from pathlib import Path

from src.evaluator.l1 import failed_l1_report
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_finalization import ReportFinalizer
from src.evaluator.l1_parent_io import make_temp_directory
from src.evaluator.l1_persistence import REAP_RESERVE_SECONDS, JsonPersistence


def recommit_resource_failure(spec, observed, invalidation, *, persistence: JsonPersistence):
    previous = Path(observed["report_path"])
    if not previous.is_absolute() or previous.name != "report.json":
        raise ValueError("Absolute report.json predecessor required")
    failure = InspectionFailure(
        "infrastructure_error", "RESOURCE_PROVENANCE_UNAVAILABLE",
        "Source, baseline, seed resources or canonical derivation failed final audit",
    )
    # The exact previous ACK remains inspectable even if its files are now
    # corrupt. Do not reread/re-hash files to bless a newer, unacknowledged copy.
    predecessor = {
        "path": str(previous), "evidence_path": observed.get("evidence_path"),
        "finalization": observed.get("finalization"),
        "role": "historical_only_not_current_result",
    }
    transaction = persistence.cleanup_transaction()
    try:
        prepared = make_temp_directory(
            previous.parent,
            deadline=transaction.cleanup_deadline - REAP_RESERVE_SECONDS,
            prefix="resource-invalidation-",
        )
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        error.resource_invalidation = invalidation
        error.superseded_report = predecessor
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        failure.resource_invalidation = invalidation
        failure.superseded_report = predecessor
        failure.path_io = getattr(error, "parent_io", None)
        raise failure from error
    output = Path(prepared["result"]["path"])
    report = {key: observed[key] for key in (
        "task_id", "task_type", "trial_id", "board", "evaluation_kind",
        "instruction_sha256", "artifact_sha256", "software", "evaluation_seconds",
    ) if key in observed}
    report.update(
        failed_l1_report(spec, failure),
        scoring_failed=True, resource_integrity_passed=False,
        resource_audit_failure=failure.reason, provenance_status="unverified",
        not_measurable=True, resource_invalidation=invalidation,
        superseded_report=predecessor,
        scoring_execution_policy="not_recomputed_prior_score_retained_as_history",
        report_path=str(output / "report.json"), evidence_path=str(output / "evidence.json"),
    )
    report["gates"]["resources"] = report["gates"].pop("compute")
    evidence = {
        "protocol": "l1-resource-invalidation-evidence-v1", "spec_sha256": spec.digest,
        "resource_invalidation": invalidation, "superseded_report": predecessor,
        "path_io": [prepared["execution"]],
        "reason": failure.reason,
    }
    return ReportFinalizer(spec, output, persistence.deadline, persistence=transaction).finish(report, evidence)
