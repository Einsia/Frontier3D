"""Validate trusted inspector results before a reproduction consumer uses them.

ACK consistency is not storage authenticity. File reads are isolated and share
the caller's deadline; Python object equality remains cooperative, not hard
preemptible. Failed observations are retained by the caller, never accepted here.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from .l1_failures import InspectionFailure
from .l1_persistence_receipt import (
    validate_persistence_receipt,
    validate_persistence_session,
)
from .l1_result import read_result


def _require(condition, reason):
    if not condition:
        raise ValueError(f"Inspector receipt: {reason}")


def _reaped(row):
    return (isinstance(row, dict) and type(row.get("pid")) is int and row["pid"] > 0
            and row.get("process_group") == row["pid"] and row.get("leader_reaped") is True
            and row.get("group_kill_sent") is True and type(row.get("return_code")) is int and row["return_code"] == 0
            and row.get("status") == "completed")


def _validate_inspection(result, *, scene: Path, spec: Path, deadline: float,
                         frame: int, frames: tuple[int, ...] | None, compare_returned: bool) -> dict:
    """Require actual metadata ACK plus independent record/facts reload.

    Only the returned session's last write to the inspector record can confirm it.
    An existing file, even one marked completed, is not a substitute for that ACK.
    """
    reads = []
    try:
        if time.monotonic() >= deadline:
            raise InspectionFailure("infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
                                    "No inspection receipt reload after deadline")
        _require(isinstance(result, dict), "result missing")
        record = result.get("inspector_execution")
        _require(isinstance(record, dict), "execution missing")
        _require(record.get("protocol") == "l1-inspector-execution-v1" and _reaped(record),
                 "execution/cleanup incomplete")
        work = record.get("deadline_monotonic")
        _require(type(work) in (int, float) and math.isfinite(work)
                 and (not compare_returned or work <= deadline),
                 "inspection deadline exceeds consumer deadline")
        _require(record.get("record_persisted") is True and isinstance(record.get("record_path"), str),
                 "record not confirmed")
        _require(record.get("scene_path") == str(scene) and record.get("spec_path") == str(spec)
                 and record.get("frame") == frame
                 and record.get("frames") == (list(frames) if frames is not None else None),
                 "input/frame binding mismatch")
        preparation = record.get("launch_preparation", {})
        _require(isinstance(preparation, dict), "launch preparation invalid")
        worker = preparation.get("execution")
        _require(preparation.get("action") == "prepare_inspector" and _reaped(worker)
                 and worker.get("deadline_monotonic") == work, "launch preparation missing")
        _require(worker.get("finished_monotonic", math.inf) <= work, "late launch preparation")
        _require(_reaped(record.get("log_io")), "log cleanup incomplete")
        session = result.get("inspector_persistence")
        rows, cleanup = validate_persistence_session(session, evaluation_deadline=work)
        _require(0 < len(rows) <= 2 and all(isinstance(row, dict) for row in rows), "unexpected metadata writes")
        path = Path(record["record_path"])
        matching = [row for row in rows if row.get("path") == str(path)]
        _require(bool(matching), "metadata ACK missing")
        latest = matching[-1]
        validate_persistence_receipt(latest, path=path, evaluation_deadline=work,
                                     cleanup_deadline=cleanup, scope="evaluation")
        saved, reception = read_result(path, deadline=deadline, max_bytes=16 * 1024 * 1024)
        reads.append(reception)
        _require(reception["received_sha256"] == latest["sha256"]
                 and reception["bytes_received"] == latest["bytes"], "metadata bytes changed")
        _require(saved == {key: value for key, value in record.items() if key != "record_path"},
                 "returned execution differs from acknowledged record")
        _require(isinstance(record.get("json_io"), dict), "facts reads missing")
        original = record["json_io"].get("facts.json")
        _require(_reaped(original) and original.get("deadline_monotonic") == work,
                 "facts read/cleanup missing")
        facts_path = path.parent / "facts.json"
        _require(original.get("source_path") == str(facts_path), "facts path mismatch")
        facts, reception = read_result(facts_path, deadline=deadline, max_bytes=256 * 1024 * 1024)
        reads.append(reception)
        _require(reception["received_sha256"] == original["received_sha256"]
                 and reception["bytes_received"] == original["bytes_received"], "facts bytes changed")
        if compare_returned:
            _require(facts == {key: value for key, value in result.items()
                               if key not in {"inspector_execution", "inspector_persistence"}},
                     "returned facts differ from acknowledged bytes")
        if time.monotonic() >= deadline:
            raise InspectionFailure("infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
                                    "Inspection validation exhausted shared deadline")
        return {"protocol": "l1-inspection-validation-v1", "status": "verified",
                "record_path": str(path), "record_sha256": latest["sha256"],
                "facts_sha256": original["received_sha256"], "reads": reads,
                "deadline_monotonic": deadline, "finished_monotonic": time.monotonic(),
                "scope": "trusted_receipt_consistency_not_storage_authenticity"}
    except (ValueError, TypeError, KeyError, OSError) as error:
        failure = InspectionFailure("infrastructure_error", "INSPECTION_RECEIPT_INVALID", str(error))
        failure.inspection_validation_io = reads
        raise failure from error
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        extra = getattr(error, "result_reception", None)
        error.inspection_validation_io = [*reads, *([extra] if extra is not None else [])]
        raise


def validate_inspection(result, *, scene: Path, spec: Path, deadline: float,
                        frame: int = 1, frames: tuple[int, ...] | None = None) -> dict:
    """Verify the facts being consumed against their actual record and ACK."""
    return _validate_inspection(result, scene=scene, spec=spec, deadline=deadline,
                                frame=frame, frames=frames, compare_returned=True)


def reload_inspection(record, persistence, *, scene: Path, spec: Path, deadline: float,
                      frame: int = 1, frames: tuple[int, ...] | None = None) -> dict:
    """Reopen historically confirmed bytes; never renew their original deadline.

    The publication/review read has its own caller-supplied deadline. It does
    not replace the historical inspection or persistence deadline in the ACK.
    Facts need not be duplicated in the outer record: the original confirmed
    read hash binds them, and both metadata and facts are independently reloaded.
    """
    return _validate_inspection({"inspector_execution": record, "inspector_persistence": persistence},
                                scene=scene, spec=spec, deadline=deadline,
                                frame=frame, frames=frames, compare_returned=False)
