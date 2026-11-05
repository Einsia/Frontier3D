"""Killable, evaluator-owned L1 CPU jobs with JSON-only IPC.

This contains trusted numerical/scoring code, not candidate execution. It is
not a security sandbox. A shared deadline covers input encoding, launch, work
and result decoding; cleanup is capped separately. No late output is accepted.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .l1_budget import DeadlineBudget
from .l1_failures import InspectionFailure
from .l1_log_io import LogSink
from .l1_parent_io import ensure_directory, make_temp_directory
from .l1_persistence import JsonPersistence
from .l1_request import prepare_request
from .l1_result import read_result

COMPUTE_PROTOCOL = "l1-compute-v1"
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
CLEANUP_SECONDS = 2.0
OPERATIONS = {
    "geometry_scene",
    "score",
    "reproduction_frame",
    "reproduction_sequence",
    "state_return",
    "compiled_material_fields",
    "rigid_shape",
    "solid_clearance",
    "bore_sections",
    "machined_sleeve",
    "washer_edit",
    "edit_surface",
    "edit_hole_profiles",
    "washer_changed_area",
    "slot_plate_surface",
    "slot_plate_preservation",
    "slot_plate_structure",
    "slot_plate_edit",
    "swept_bar",
    "file_io",
}
WORKER = Path(__file__).with_name("l1_compute_worker.py")


def _command(request: Path, result: Path) -> list[str]:
    return [
        sys.executable,
        str(WORKER),
        "--request",
        str(request),
        "--result",
        str(result),
    ]


def _failure(code: str, reason: str) -> InspectionFailure:
    return InspectionFailure("infrastructure_error", code, reason)


def _guard(budget):
    if budget.exhausted:
        raise _failure(
            "EVALUATION_BUDGET_EXHAUSTED", "Compute stage exhausted its shared deadline"
        )


def _cleanup(process, record):
    started = time.monotonic()
    try:
        os.killpg(process.pid, signal.SIGKILL)
        record["group_kill_sent"] = True
    except ProcessLookupError:
        record["group_kill_sent"] = True
    except OSError as error:
        record.update(group_kill_sent=False, cleanup_error=type(error).__name__)
    try:
        process.wait(timeout=CLEANUP_SECONDS)
        record["leader_reaped"] = True
    except subprocess.TimeoutExpired:
        record["leader_reaped"] = False
    record.update(
        return_code=process.returncode,
        cleanup_seconds=time.monotonic() - started,
        cleanup_ack=bool(record.get("group_kill_sent") and record.get("leader_reaped")),
    )


def _terminal_status(error):
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return "interrupted"
    code = getattr(error, "code", None)
    if code == "EVALUATION_BUDGET_EXHAUSTED":
        return "budget_exhausted"
    if code in {"COMPUTE_INPUT_LIMIT", "COMPUTE_REQUEST_PREPARATION_FAILED"}:
        return "request_failed"
    if code == "COMPUTE_LAUNCH_ERROR":
        return "launch_error"
    if code == "COMPUTE_CLEANUP_TIMEOUT":
        return "cleanup_failed"
    if code in {
        "JSON_PERSISTENCE_FAILED",
        "JSON_PERSISTENCE_LIMIT",
        "PERSISTENCE_AFTER_CLEANUP",
    }:
        return "record_failed"
    return "protocol_error"


def run_compute(
    operation: str,
    payload: dict[str, Any],
    *,
    output: Path,
    deadline: float | None,
    timeout: float = 900.0,
) -> dict[str, Any]:
    if operation not in OPERATIONS:
        raise ValueError("Unknown L1 compute operation")
    started = time.monotonic()
    # Validate a supplied timestamp before deriving a local allowance from it.
    budget = DeadlineBudget.start(timeout, deadline=deadline, started=started)
    if deadline is not None:
        budget = DeadlineBudget.start(
            max(1.0, deadline - started), deadline=deadline, started=started
        )
    record: dict[str, Any] = {
        "protocol": COMPUTE_PROTOCOL,
        "operation": operation,
        "request_sha256": None,
        "status": "not_started",
        "state_history": ["not_started"],
        "pid": None,
        "deadline_monotonic": budget.deadline,
        "cleanup_limit_seconds": CLEANUP_SECONDS,
        "containment": "trusted_process_group_not_security_sandbox",
        "metadata_acknowledgement": "returned_record_persistence_not_file_presence",
        "state_evidence_protocol": "l1-compute-state-files-v1",
        "path_io": [],
        "remaining_parent_io": ["launch_setup", "logs"],
    }

    def set_status(value: str) -> None:
        """Append only valid compute states to the trusted worker record."""
        previous = record.get("status")
        allowed = {
            "not_started": {"prepared", "budget_exhausted", "request_failed", "launch_error", "record_failed", "protocol_error", "interrupted"},
            "prepared": {"running", "budget_exhausted", "request_failed", "launch_error", "record_failed", "protocol_error", "interrupted"},
            "running": {"collecting", "budget_exhausted", "cleanup_failed", "protocol_error", "record_failed", "interrupted"},
            "collecting": {"completed", "budget_exhausted", "protocol_error", "record_failed", "interrupted"},
            "completed": {"record_failed", "budget_exhausted", "interrupted"},
        }
        if value != previous and value not in allowed.get(previous, set()):
            raise RuntimeError(f"invalid compute state transition {previous!r} -> {value!r}")
        record["status"] = value
        if value != previous:
            record["state_history"].append(value)

    # Directory creation and temporary workspace allocation are filesystem
    # operations of their own. Keep them out of the supervising process and
    # bind their receipts to the same evaluator deadline.
    try:
        if budget.exhausted:
            raise _failure(
                "EVALUATION_BUDGET_EXHAUSTED",
                "No compute job started after shared deadline",
            )
        if os.name != "posix":
            raise _failure(
                "COMPUTE_ISOLATION_UNAVAILABLE", "L1 compute groups currently require POSIX"
            )
        prepared = ensure_directory(output, deadline=budget.deadline, parents=True)
        record["path_io"].append(prepared["execution"])
        temporary = make_temp_directory(output, deadline=budget.deadline, prefix="compute-")
        record["path_io"].append(temporary["execution"])
    except (InspectionFailure, OSError, ValueError, TypeError, KeyboardInterrupt, SystemExit) as error:
        set_status(_terminal_status(error))
        record["budget"] = budget.record("compute")
        failure = error if isinstance(error, (InspectionFailure, KeyboardInterrupt, SystemExit)) else _failure(
            "COMPUTE_PATH_IO_ERROR", type(error).__name__
        )
        record.update(
            failure_evidence_protocol="l1-compute-failure-v1",
            failure={"code": failure.code if isinstance(failure, InspectionFailure) else type(failure).__name__,
                     "status": getattr(failure, "status", "infrastructure_error")},
            record_persisted=False,
        )
        failure.compute_execution = {
            **record, "record_path": None,
            "record_persistence": JsonPersistence(budget.deadline).evidence(),
        }
        raise failure
    directory = Path(temporary["result"]["path"]).resolve()
    request, result_path = directory / "request.json", directory / "result.json"
    record_path = directory / "worker_record.json"
    persistence = JsonPersistence(budget.deadline)
    save_sequence = 0

    def save(*, cleanup=False):
        nonlocal save_sequence
        # A create-only historical file precedes the mutable checkpoint. Both
        # contain identical bytes; a snapshot alone is not a checkpoint ACK.
        # Failed attempts consume their sequence number too, never overwrite
        # an installed but unacknowledged state during failure cleanup.
        state_path = directory / f"state-{save_sequence:03d}-{record['status']}.json"
        save_sequence += 1
        record["record_persisted"] = True
        try:
            persistence.write(state_path, record, cleanup=cleanup, replace=False)
            return persistence.write(record_path, record, cleanup=cleanup)
        except BaseException:
            record["record_persisted"] = False
            raise

    def execution():
        # A file cannot include its own final hash. Keep the accepted writes
        # outside its payload, and bind each ACK to exact bytes and deadline.
        return {
            **record,
            "record_path": str(record_path),
            "record_persistence": persistence.evidence(),
        }

    try:
        save()
        preparation = prepare_request(
            request,
            {
                "protocol": COMPUTE_PROTOCOL,
                "operation": operation,
                "payload": payload,
                "deadline": budget.deadline,
            },
            deadline=budget.deadline,
            max_bytes=MAX_MESSAGE_BYTES,
        )
        set_status("prepared")
        record.update(
            request_sha256=preparation["request_sha256"],
            request_preparation=preparation,
        )
        save()
        _guard(budget)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT"}
        }
        environment.update(
            OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1"
        )
        log_sink = None
        try:
            _guard(budget)
            log_sink = LogSink(directory / "worker.log", budget.deadline)
            log_stream = log_sink.start()
            try:
                _guard(budget)
                process = subprocess.Popen(
                    _command(request, result_path),
                    stdout=log_stream,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    cwd=Path(__file__).resolve().parents[2],
                    env=environment,
                    start_new_session=True,
                )
            finally:
                # The target inherits the pipe; the supervisor must not keep a
                # duplicate writer open or the sink could wait for EOF forever.
                log_stream.close()
            set_status("running")
            record.update(
                pid=process.pid, process_group=process.pid,
                state_transition="prepared_to_running",
            )
            try:
                # Cleanup encloses the metadata write too: its failure
                # must never strand an already launched computation.
                save()
                _guard(budget)
                try:
                    process.wait(timeout=budget.remaining)
                except subprocess.TimeoutExpired as error:
                    raise _failure(
                        "EVALUATION_BUDGET_EXHAUSTED",
                        "Compute terminated at deadline",
                    ) from error
            finally:
                _cleanup(process, record)
                if log_sink is not None:
                    record["log_io"] = log_sink.finish(cleanup=record.get("status") != "running")
        except OSError as error:
            raise _failure("COMPUTE_LAUNCH_ERROR", type(error).__name__) from error
        if not record["leader_reaped"] or not record["group_kill_sent"]:
            raise _failure(
                "COMPUTE_CLEANUP_TIMEOUT", "Compute group cleanup incomplete"
            )
        _guard(budget)
        if record.get("log_io", {}).get("status") != "completed" and process.returncode == 0:
            raise _failure("COMPUTE_LOG_IO_ERROR", "Worker log was not durably acknowledged")
        if process.returncode != 0:
            raise _failure(
                "COMPUTE_PROTOCOL_ERROR", "Compute worker exited unsuccessfully"
            )
        set_status("collecting")
        record.update(
            state_transition="running_to_collecting",
            budget=budget.record("compute"),
        )
        save()
        result, reception = read_result(
            result_path, deadline=budget.deadline, max_bytes=MAX_MESSAGE_BYTES
        )
        record["result_reception"] = reception
        if (
            not isinstance(result, dict)
            or set(result) != {"protocol", "operation", "result"}
            or result["protocol"] != COMPUTE_PROTOCOL
            or result["operation"] != operation
            or not isinstance(result["result"], dict)
        ):
            raise _failure("COMPUTE_PROTOCOL_ERROR", "Invalid compute result envelope")
        _guard(budget)
        set_status("completed")
        record.update(
            state_transition="collecting_to_completed",
            result_sha256=reception["result_sha256"],
            budget=budget.record("compute"),
        )
        save()
        _guard(budget)
    except (
        InspectionFailure,
        OSError,
        ValueError,
        TypeError,
        KeyboardInterrupt,
        SystemExit,
    ) as error:
        for key in ("request_preparation", "result_reception"):
            if hasattr(error, key) and not (
                key == "request_preparation" and hasattr(error, "json_persistence")
            ):
                record[key] = getattr(error, key)
        failure = (
            error
            if isinstance(error, (InspectionFailure, KeyboardInterrupt, SystemExit))
            else _failure("COMPUTE_PROTOCOL_ERROR", type(error).__name__)
        )
        set_status(_terminal_status(failure))
        record.update(
            budget=budget.record("compute"),
            failure_evidence_protocol="l1-compute-failure-v1",
            failure={
                "code": failure.code if isinstance(failure, InspectionFailure) else type(failure).__name__,
                "status": getattr(failure, "status", "infrastructure_error"),
            },
        )
        try:
            save(cleanup=True)
        except (InspectionFailure, OSError, ValueError, TypeError, KeyboardInterrupt, SystemExit) as persistence_error:
            record["persistence_failure"] = getattr(
                persistence_error, "code", type(persistence_error).__name__
            )
        failure.compute_execution = execution()
        if failure is error:
            raise
        raise failure from error
    result["result"]["compute_execution"] = execution()
    return result["result"]
