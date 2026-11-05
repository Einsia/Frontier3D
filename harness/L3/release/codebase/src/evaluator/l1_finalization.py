"""Deadline-bound evidence/report publication; files alone are not a commit.

The returned ACK belongs in the caller's trusted record. On-disk report bytes
remain marked pending: a later consumer must obtain the accepted ACK, not infer
completion from file presence. This does not implement the caller's own I/O.
"""

from __future__ import annotations

import time
from pathlib import Path

from .l1 import failed_l1_report
from .l1_failures import InspectionFailure
from .l1_persistence import JsonPersistence
from .l1_persistence_receipt import (
    validate_persistence_receipt,
    validate_persistence_session,
)
from .l1_result import read_result

PROTOCOL = "l1-report-finalization-v1"


def _accepted_writes(value):
    """Validate all three accepted writes; does not authenticate or read files."""
    if not isinstance(value, dict) or value.get("protocol") != PROTOCOL or value.get("status") != "completed":
        raise ValueError("Completed report ACK required")
    manifest_value = value.get("manifest_path")
    if not isinstance(manifest_value, str) or Path(manifest_value).name != "finalization.json":
        raise ValueError("Finalization path required")
    manifest = Path(manifest_value)
    end = value.get("deadline_monotonic")
    rows, cleanup = validate_persistence_session(value.get("persistence"), evaluation_deadline=end)
    if len(rows) != 3:
        raise ValueError("Exactly three finalization writes required")
    paths = [manifest.with_name("evidence.json"), manifest.with_name("report.json"), manifest]
    hashes = [value.get("evidence_sha256"), value.get("report_sha256"), value.get("manifest_sha256")]
    previous = None
    for row, path, digest in zip(rows, paths, hashes, strict=True):
        if digest is None:
            raise ValueError("Finalization hash required")
        validate_persistence_receipt(
            row, path=path, digest=digest, evaluation_deadline=end, cleanup_deadline=cleanup,
            scope="evaluation" if cleanup is None else "failure_cleanup",
        )
        if previous is not None and row["execution"]["started_monotonic"] < previous:
            raise ValueError("Finalization write ordering mismatch")
        previous = row["execution"]["finished_monotonic"]
    if value.get("receipt") != rows[-1]:
        raise ValueError("Finalization manifest ACK not in accepted session")
    return dict(zip(("evidence", "report", "manifest"), rows, strict=True))


def is_finalized(report):
    """Legacy reports retain their old policy; declared new reports fail closed."""
    if "finalization" not in report:
        return True
    try:
        _accepted_writes(report["finalization"])
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
    if report["finalization"]["persistence"]["cleanup_deadline_monotonic"] is not None:
        return _unavailable(report)
    return True


def _unavailable(report):
    return (isinstance(report, dict) and report.get("G") == 0
            and report.get("S_core") == 0 and report.get("case_pass") is False
            and (report.get("scoring_failed") is True or report.get("budget_exhausted") is True))


def compact_evidence(spec, evidence, output, reason):
    return {
        "protocol": "l1-failure-evidence-v1",
        "spec_sha256": spec.digest,
        "artifact_sha256": evidence.get("artifact_sha256", {}),
        "inspection_failures": evidence.get("inspection_failures", []),
        "infrastructure_errors": evidence.get("infrastructure_errors", []),
        "measurement_failures": evidence.get("measurement_failures", {}),
        "raw_evidence_directory": str(output),
        "reason": reason,
    }


def load_finalized_report(path, accepted, *, deadline):
    """Reopen only with an ACK from the caller's already validated record.

    Validate exact report, manifest and evidence bytes; do not reconstruct an
    acknowledgement from a pending file. This is not ACK authentication: that
    remains the caller's trusted-record/source binding responsibility.
    """
    if type(accepted) is dict and accepted.get("status") in {"failed", "interrupted"}:
        # A failed publication can have acknowledged the minimal zero-score
        # report without managing to write evidence/manifest. Reopen only
        # that exact acknowledged file, never an earlier pending success.
        try:
            if accepted.get("protocol") != PROTOCOL:
                raise ValueError("Failure ACK protocol mismatch")
            attempts, cleanup = validate_persistence_session(
                accepted.get("persistence"), evaluation_deadline=accepted.get("deadline_monotonic")
            )
            writes = [row for row in attempts if isinstance(row, dict) and row.get("path") == str(path)]
            if not writes:
                raise ValueError("Failure report ACK missing")
            # Do not skip a later unacknowledged write and resurrect an old
            # successful ACK, even if the old bytes happen to remain on disk.
            latest = validate_persistence_receipt(
                writes[-1], path=path, evaluation_deadline=accepted["deadline_monotonic"],
                cleanup_deadline=cleanup, scope="failure_cleanup",
            )
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise InspectionFailure(
                "infrastructure_error",
                "REPORT_NOT_FINALIZED",
                "No acknowledged failure report",
            ) from error
        report, receipt = read_result(
            path, deadline=deadline, max_bytes=64 * 1024 * 1024
        )
        if (
            receipt["result_sha256"] != latest["sha256"]
            or receipt["bytes_received"] != latest["bytes"]
            or type(report) is not dict
            or report.get("G") != 0
            or report.get("S_core") != 0
            or report.get("case_pass") is not False
            or report.get("scoring_failed") is not True
            or not isinstance(report.get("finalization"), dict)
            or report["finalization"].get("status") != accepted["status"]
        ):
            raise InspectionFailure(
                "infrastructure_error",
                "REPORT_FINALIZATION_MISMATCH",
                "Failure report binding mismatch",
            )
        report["finalization"] = accepted
        return report
    try:
        accepted_files = _accepted_writes(accepted)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise InspectionFailure(
            "infrastructure_error",
            "REPORT_NOT_FINALIZED",
            "Accepted trusted report ACK required",
        ) from error
    report, report_read = read_result(
        path, deadline=deadline, max_bytes=64 * 1024 * 1024
    )
    manifest_path = path.with_name("finalization.json")
    manifest, manifest_read = read_result(
        manifest_path, deadline=deadline, max_bytes=64 * 1024 * 1024
    )
    if (
        type(report) is not dict
        or type(manifest) is not dict
        or accepted["manifest_path"] != str(manifest_path)
        or report_read["result_sha256"] != accepted.get("report_sha256")
        or manifest_read["result_sha256"] != accepted["manifest_sha256"]
        or manifest_read["bytes_received"] != accepted_files["manifest"]["bytes"]
        or report_read["bytes_received"] != accepted_files["report"]["bytes"]
        or manifest.get("protocol") != PROTOCOL
        or manifest.get("status") != "prepared"
        or not isinstance(report.get("finalization"), dict)
        or report["finalization"].get("status") != "pending"
        or report.get("finalization", {}).get("manifest_path") != str(manifest_path)
        or report.get("spec_sha256") != manifest.get("spec_sha256")
        or report.get("task_id") != manifest.get("task_id")
        or manifest.get("deadline_monotonic") != accepted.get("deadline_monotonic")
        or manifest.get("result_kind") != (
            "unavailable" if accepted["persistence"]["cleanup_deadline_monotonic"] is not None else "measured"
        )
        or (accepted["persistence"]["cleanup_deadline_monotonic"] is not None and not _unavailable(report))
    ):
        raise InspectionFailure(
            "infrastructure_error",
            "REPORT_FINALIZATION_MISMATCH",
            "Report/manifest ACK binding mismatch",
        )
    files = manifest.get("files")
    evidence_path = path.with_name("evidence.json")
    if (
        type(files) is not dict
        or set(files) != {"report", "evidence"}
        or any(type(files[key]) is not dict for key in files)
        or files["report"].get("path") != str(path)
        or files["report"].get("sha256") != accepted["report_sha256"]
        or files["evidence"].get("path") != str(evidence_path)
        or files["evidence"].get("sha256") != accepted.get("evidence_sha256")
        or files["report"] != accepted_files["report"]
        or files["evidence"] != accepted_files["evidence"]
    ):
        raise InspectionFailure(
            "infrastructure_error",
            "REPORT_FINALIZATION_MISMATCH",
            "Finalized file set mismatch",
        )
    _, evidence_read = read_result(
        evidence_path, deadline=deadline, max_bytes=64 * 1024 * 1024
    )
    if (evidence_read["result_sha256"] != accepted["evidence_sha256"]
            or evidence_read["bytes_received"] != accepted_files["evidence"]["bytes"]):
        raise InspectionFailure(
            "infrastructure_error",
            "REPORT_FINALIZATION_MISMATCH",
            "Finalized evidence changed",
        )
    report["finalization"] = accepted
    return report


class ReportFinalizer:
    def __init__(self, spec, output, deadline, *, persistence=None):
        self.spec, self.output, self.deadline = spec, output, deadline
        if persistence is not None and (
            not isinstance(persistence, JsonPersistence)
            or persistence.deadline != deadline or persistence.records
        ):
            raise ValueError("Fresh finalization transaction with matching deadline required")
        self.persistence = persistence if persistence is not None else JsonPersistence(deadline)
        self.manifest = output / "finalization.json"

    def _marker(self, status):
        return {
            "protocol": PROTOCOL,
            "status": status,
            "manifest_path": str(self.manifest),
            "deadline_monotonic": self.deadline,
            "acceptance": "trusted_returned_ack_required_not_file_presence",
        }

    def finish(self, report, evidence):
        report["finalization"] = self._marker("pending")
        cleanup = bool(report.get("scoring_failed") or report.get("budget_exhausted"))
        try:
            evidence_ack = self.persistence.write(
                self.output / "evidence.json", evidence, cleanup=cleanup
            )
            report_ack = self.persistence.write(
                self.output / "report.json", report, cleanup=cleanup
            )
            manifest = {
                "protocol": PROTOCOL,
                "status": "prepared",
                "spec_sha256": self.spec.digest,
                "task_id": report["task_id"],
                "deadline_monotonic": self.deadline,
                "result_kind": "unavailable" if cleanup else "measured",
                "files": {"evidence": evidence_ack, "report": report_ack},
                "acceptance": "manifest_bytes_also_require_returned_ack",
            }
            receipt = self.persistence.write(self.manifest, manifest, cleanup=cleanup)
            # Normal scores never receive a post-deadline acceptance. Failure
            # evidence may finish in the single, separately bounded allowance.
            if not cleanup and time.monotonic() >= self.deadline:
                raise InspectionFailure(
                    "infrastructure_error",
                    "EVALUATION_BUDGET_EXHAUSTED",
                    "Late finalization rejected",
                )
        except (InspectionFailure, KeyboardInterrupt, SystemExit) as failure:
            failed = self.fail(report, evidence, failure)
            if isinstance(failure, (KeyboardInterrupt, SystemExit)):
                failure.finalization_report = failed
                raise
            return failed
        report["finalization"] = {
            **self._marker("completed"),
            "manifest_sha256": receipt["sha256"],
            "report_sha256": report_ack["sha256"],
            "evidence_sha256": evidence_ack["sha256"],
            "receipt": receipt,
            "persistence": self.persistence.evidence(),
        }
        return report

    def fail(self, report, evidence, error):
        interrupted = isinstance(error, (KeyboardInterrupt, SystemExit))
        failure = (
            error
            if isinstance(error, InspectionFailure)
            else InspectionFailure(
                "infrastructure_error",
                "FINALIZATION_INTERRUPTED" if interrupted else "FINALIZATION_FAILED",
                type(error).__name__,
            )
        )
        # Rebuild scoring fields from the frozen spec, never retry a metric or
        # copy candidate-sized geometry into a post-budget failure payload.
        unavailable = failed_l1_report(self.spec, failure)
        failed = {
            key: report[key]
            for key in (
                "task_id",
                "task_type",
                "trial_id",
                "board",
                "evaluation_kind",
                "instruction_sha256",
                "artifact_sha256",
                "software",
                "evaluation_seconds",
                "geometry_protocol_path",
                "evidence_path",
                "report_path",
                "resource_invalidation",
                "resource_integrity_passed",
                "resource_audit_failure",
                "provenance_status",
                "not_measurable",
                "superseded_report",
                "scoring_execution_policy",
                "compute_execution",
                "scoring_failure",
            )
            if key in report
        }
        failed.update(
            unavailable,
            scoring_failed=True,
            persistence_failed=True,
            budget_exhausted=bool(report.get("budget_exhausted"))
            or time.monotonic() >= self.deadline,
            errors=[failure.code],
            finalization=self._marker("interrupted" if interrupted else "failed"),
        )
        failed["gates"]["persistence"] = failed["gates"].pop("compute")
        if report.get("scoring_failed") and "compute" in report.get("gates", {}):
            failed["gates"]["compute"] = report["gates"]["compute"]
        failed["errors"] = list(dict.fromkeys([*report.get("errors", []), failure.code]))
        if "resources" in report.get("gates", {}):
            failed["gates"]["resources"] = report["gates"]["resources"]
        failed["failure_report_policy"] = (
            "spec_bounded_no_metric_retry_stage_evidence_retained"
        )
        detail = {
            "status": failure.status,
            "code": failure.code,
            "reason": failure.reason,
            "scopes": ["/finalization"],
        }
        compact = compact_evidence(
            self.spec,
            {},
            self.output,
            "Finalization unavailable; stage-local evidence retained",
        )
        compact.update(
            artifact_sha256=report.get("artifact_sha256", {}),
            inspection_failures=[detail],
            infrastructure_errors=[detail],
        )
        # Prioritize replacing a possibly installed success report. All of
        # these writes share ONE failure deadline; no fresh timer per file.
        for path, value in (
            (self.output / "report.json", failed),
            (self.output / "evidence.json", compact),
            (self.manifest, {**self._marker("failed"), "failure": detail}),
        ):
            try:
                self.persistence.write(path, value, cleanup=True)
            except InspectionFailure:
                # In-memory evidence remains authoritative when storage is
                # blocked. Do not fall back to an unbounded parent write.
                continue
        failed["finalization"]["persistence"] = self.persistence.evidence()
        return failed
