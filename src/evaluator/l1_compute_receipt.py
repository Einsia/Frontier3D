"""Reload a trusted L1 score receipt against its acknowledged IPC artifacts.

These are consistency checks, not authentication of candidate-supplied ACKs.
The caller must first authenticate the enclosing report and trusted record.
All file reads share the caller's deadline and the existing bounded reader.
"""

from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from .l1_failures import InspectionFailure
from .l1_persistence_receipt import (
    validate_persistence_receipt,
    validate_persistence_session,
)
from .l1_result import read_result
from .spec import EvalSpec

MAX_BYTES = 64 * 1024 * 1024
STATES = ["not_started", "prepared", "running", "collecting", "completed"]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"compute {message}")


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def compute_binding(compute: dict[str, Any]) -> dict[str, Any]:
    """Summarize accepted writes, never bless current file bytes as an ACK."""
    persistence = compute.get("record_persistence")
    rows = persistence.get("records", []) if isinstance(persistence, dict) else []
    rows = rows if isinstance(rows, list) else []
    last = rows[-1] if rows and isinstance(rows[-1], dict) else {}
    compact = {
        key: compute.get(key) for key in (
            "protocol", "operation", "status", "state_history", "request_sha256",
            "result_sha256", "record_path", "cleanup_ack", "group_kill_sent", "leader_reaped",
            "state_evidence_protocol",
            "failure_evidence_protocol", "failure", "record_persisted", "persistence_failure",
        )
    }
    compact["record_sha256"] = (
        last.get("sha256") if last.get("status") == "completed"
        and last.get("path") == compute.get("record_path")
        and compute.get("record_persisted") is True else None
    )
    compact["persistence_records"] = [
        {
            **{key: row.get(key) for key in ("path", "status", "sha256", "bytes", "scope")},
            "execution": {
                key: row["execution"].get(key)
                for key in ("status", "leader_reaped", "group_kill_sent", "commit_mode")
            } if isinstance(row.get("execution"), dict) else {},
        }
        for row in rows if isinstance(row, dict)
    ]
    return compact


def _transfer(execution: Any, *, path: Path, digest: str, size: int,
              deadline: float, writer: bool, commit_mode: str | None = None) -> None:
    label = "writer" if writer else "reader"
    _require(isinstance(execution, dict), f"{label} ACK missing")
    expected_protocol = "l1-request-preparation-v1" if writer else "l1-result-reception-v1"
    _require(execution.get("protocol") == expected_protocol, f"{label} protocol mismatch")
    _require(execution.get("status") == "completed", f"{label} did not complete")
    pid = execution.get("pid")
    _require(type(pid) is int and pid > 0 and execution.get("process_group") == pid,
             f"{label} process binding mismatch")
    _require(execution.get("leader_reaped") is True and execution.get("group_kill_sent") is True
             and type(execution.get("return_code")) is int and execution["return_code"] == 0,
             f"{label} cleanup ACK missing")
    _require(execution.get("deadline_monotonic") == deadline, f"{label} deadline mismatch")
    _require(execution.get("request_path" if writer else "source_path") == str(path),
             f"{label} path mismatch")
    _require(_digest(digest) and type(size) is int and 0 < size <= MAX_BYTES,
             f"{label} byte binding invalid")
    hash_keys = ("request_sha256", "sent_sha256") if writer else ("result_sha256", "received_sha256")
    size_keys = ("bytes", "bytes_sent") if writer else ("bytes_received",)
    _require(all(execution.get(key) == digest for key in hash_keys)
             and all(type(execution.get(key)) is int and execution[key] == size for key in size_keys),
             f"{label} hash/size mismatch")
    start = execution.get(f"{label}_started")
    finish = execution.get(f"{label}_result")
    _require(isinstance(start, dict) and isinstance(finish, dict), f"{label} process receipts missing")
    protocol = "l1-request-writer-v1" if writer else "l1-result-reader-v1"
    _require(all(row.get("protocol") == protocol and row.get("pid") == pid
                 and row.get("process_group") == pid for row in (start, finish)),
             f"{label} child receipt binding mismatch")
    _require(start.get("phase") == "started" and finish.get("phase") == "finished"
             and finish.get("status") == "completed" and finish.get("sha256") == digest
             and type(finish.get("bytes")) is int and finish["bytes"] == size,
             f"{label} child receipt incomplete")
    times = [execution.get("started_monotonic"), start.get("entered_monotonic"),
             finish.get("completed_monotonic"), execution.get("finished_monotonic"), deadline]
    _require(all(_number(value) for value in times) and times == sorted(times),
             f"{label} late or unordered ACK")
    if writer:
        _require(execution.get("worker_deadline_monotonic") == deadline,
                 "writer worker deadline mismatch")
        _require(execution.get("commit_mode") == finish.get("commit_mode") == commit_mode
                 and finish.get("directory_synced") is True, "writer durable commit ACK missing")
    else:
        metadata = finish.get("source_stat")
        _require(isinstance(metadata, dict) and metadata.get("bytes") == size,
                 "reader source size mismatch")


def _validate_failed_score(report: dict[str, Any], compute: dict[str, Any], *, deadline: float) -> dict:
    """Verify available failure artifacts, never promote them to a measured score.

    A terminal checkpoint can be uncommitted. In that case the enclosing
    trusted report binds the supervisor's failure metadata; only individually
    ACKed historical files are read, and persistence_ack remains false.
    """
    terminal = {"budget_exhausted", "request_failed", "launch_error", "cleanup_failed",
                "protocol_error", "record_failed", "interrupted"}
    _require(report.get("scoring_status") == "unavailable", "failure report not explicitly unavailable")
    history = compute.get("state_history")
    _require(compute.get("status") in terminal
             and compute.get("failure_evidence_protocol") == "l1-compute-failure-v1",
             "failure protocol/status mismatch")
    _require(isinstance(history, list) and 2 <= len(history) <= 6
             and history[:-1] == STATES[:len(history) - 1]
             and history[-1] == compute["status"], "failure state history mismatch")
    failure = compute.get("failure")
    _require(isinstance(failure, dict) and isinstance(failure.get("code"), str)
             and bool(failure["code"]) and failure.get("status") == "infrastructure_error",
             "failure attribution missing")
    _require(compute.get("state_evidence_protocol") == "l1-compute-state-files-v1"
             and type(compute.get("record_persisted")) is bool,
             "failure persistence policy missing")
    work_deadline = compute.get("deadline_monotonic")
    rows, cleanup = validate_persistence_session(
        compute.get("record_persistence"), evaluation_deadline=work_deadline,
    )
    _require(len(rows) <= 12, "failure state evidence limit exceeded")
    path_value, pid = compute.get("record_path"), compute.get("pid")
    if pid is None:
        _require("running" not in history and compute.get("process_group") is None
                 and compute.get("cleanup_ack") is not True, "unstarted failure claims execution")
    else:
        _require(type(pid) is int and pid > 0 and compute.get("process_group") == pid
                 and "running" in history, "failed process identity mismatch")
        _require(all(type(compute.get(key)) is bool
                     for key in ("cleanup_ack", "group_kill_sent", "leader_reaped"))
                 and compute["cleanup_ack"] == (compute["group_kill_sent"] and compute["leader_reaped"]),
                 "failed process cleanup evidence missing")
    if path_value is None:
        _require(not rows and pid is None and history[:-1] == STATES[:1]
                 and compute["record_persisted"] is False
                 and compute.get("request_sha256") is None
                 and "request_preparation" not in compute and "result_reception" not in compute,
                 "unstarted failure contains persisted work")
        return {"protocol": compute["protocol"], "operation": "score", "status": compute["status"],
                "failure_evidence_verified": True, "execution_started": False,
                "persistence_ack": False, "state_files_reloaded": 0,
                "request_reloaded": False, "result_reloaded": False, "cleanup_ack": None}
    _require(isinstance(path_value, str) and Path(path_value).is_absolute()
             and Path(path_value).name == "worker_record.json", "failed record path invalid")
    path = Path(path_value)
    _require(bool(rows) and cleanup is not None, "failure cleanup session missing")
    snapshots, previous, checkpoint, sequence = [], None, None, -1
    completed_states, previous_finished = set(), None
    for row in rows:
        _require(isinstance(row, dict) and isinstance(row.get("path"), str), "failure write missing")
        historical = row.get("commit_mode") == "create_only"
        if historical:
            match = re.fullmatch(r"state-(\d{3})-([a-z_]+)\.json", Path(row["path"]).name)
            _require(match is not None and sequence < int(match[1]) <= 5
                     and match[2] in history and Path(row["path"]).parent == path.parent,
                     "failure historical path/order mismatch")
            expected_index = history.index(match[2])
            _require(int(match[1]) == expected_index or (
                match[2] == compute["status"] and int(match[1]) == expected_index - 1
            ), "failure snapshot sequence does not match state")
            sequence = int(match[1])
        else:
            _require(row["path"] == str(path) and previous is not None
                     and previous.get("commit_mode") == "create_only"
                     and previous.get("status") == "completed", "failure checkpoint has no snapshot")
            checkpoint = row
        if row.get("status") == "completed":
            validate_persistence_receipt(
                row, path=Path(row["path"]), evaluation_deadline=work_deadline,
                cleanup_deadline=cleanup, commit_mode="create_only" if historical else "replace_regular",
            )
            _require(previous_finished is None or previous_finished <= row["execution"]["started_monotonic"],
                     "failure ACK ordering mismatch")
            previous_finished = row["execution"]["finished_monotonic"]
            if historical:
                snapshot, reception = read_result(Path(row["path"]), deadline=deadline, max_bytes=MAX_BYTES)
                _require(reception["result_sha256"] == row["sha256"]
                         and reception["bytes_received"] == row["bytes"], "failure historical hash mismatch")
                _require(isinstance(snapshot, dict) and snapshot.get("status") == match[2]
                         and snapshot.get("state_history") == history[:history.index(match[2]) + 1]
                         and snapshot.get("record_persisted") is True, "failure snapshot evolution mismatch")
                for key in ("protocol", "operation", "deadline_monotonic", "state_evidence_protocol",
                            "containment", "metadata_acknowledgement"):
                    _require(snapshot.get(key) == compute.get(key), f"failure snapshot {key} mismatch")
                for key in ("pid", "request_sha256", "request_preparation", "result_reception"):
                    if snapshot.get(key) is not None:
                        _require(snapshot[key] == compute.get(key), f"failure snapshot {key} drift")
                if match[2] in STATES:
                    index = STATES.index(match[2])
                    _require(row["scope"] == "evaluation"
                             and snapshot.get("pid") == (pid if index >= 2 else None)
                             and snapshot.get("request_sha256") == (compute.get("request_sha256") if index >= 1 else None)
                             and ("request_preparation" in snapshot) == (index >= 1)
                             and ("result_reception" in snapshot) == (index >= 4),
                             "failure normal snapshot has impossible fields")
                else:
                    _require(row["scope"] == "failure_cleanup", "terminal failure outside cleanup")
                snapshots.append(snapshot)
            else:
                _require(row["sha256"] == previous["sha256"] and row["bytes"] == previous["bytes"],
                         "failure snapshot/checkpoint bytes mismatch")
                completed_states.add(snapshots[-1]["status"])
        else:
            # An attempted write may have installed bytes before ACK failure.
            # Never read or infer a durable commit from those bytes.
            _require(row.get("status") in {"failed", "not_started", "budget_exhausted",
                                          "interrupted", "limit_exceeded", "error"},
                     "unknown failed persistence status")
            _require(row.get("sha256") is None and row.get("bytes") is None,
                     "unacknowledged failure write claims committed bytes")
        previous = row
    # Every state preceding the last normal state must have completed both
    # writes. Only that last state can have been interrupted during saving.
    _require(set(history[:-2]) <= completed_states, "failure history omitted a mandatory state ACK")
    persisted = compute["record_persisted"]
    if persisted:
        _require(checkpoint is rows[-1] and checkpoint["status"] == "completed"
                 and snapshots and snapshots[-1]["status"] == compute["status"],
                 "terminal failure checkpoint ACK missing")
        stored, reception = read_result(path, deadline=deadline, max_bytes=MAX_BYTES)
        _require(reception["result_sha256"] == checkpoint["sha256"]
                 and reception["bytes_received"] == checkpoint["bytes"], "failure checkpoint hash mismatch")
        expected = {key: value for key, value in compute.items()
                    if key not in {"record_path", "record_persistence", "record_sha256"}}
        _require(stored == expected == snapshots[-1], "failure checkpoint content mismatch")
    else:
        _require(isinstance(compute.get("persistence_failure"), str), "uncommitted failure reason missing")
        _require(rows[-1].get("status") != "completed"
                 or rows[-1].get("commit_mode") == "create_only"
                 or not snapshots or snapshots[-1]["status"] != compute["status"],
                 "uncommitted failure hides accepted terminal checkpoint")
    request_read = result_read = False
    preparation = compute.get("request_preparation", {})
    if preparation.get("status") == "completed":
        request_path = path.with_name("request.json")
        request, reception = read_result(request_path, deadline=deadline, max_bytes=MAX_BYTES)
        _transfer(preparation, path=request_path, digest=reception["result_sha256"],
                  size=reception["bytes_received"], deadline=work_deadline, writer=True, commit_mode="create_only")
        _require(isinstance(request, dict) and request.get("protocol") == compute["protocol"]
                 and request.get("operation") == "score" and request.get("deadline") == work_deadline
                 and reception["result_sha256"] == compute.get("request_sha256"), "failure request mismatch")
        _require(EvalSpec.from_dict(request["payload"]["spec"]).digest == report.get("spec_sha256"),
                 "failure request specification mismatch")
        request_read = True
    else:
        _require(pid is None and compute.get("request_sha256") is None, "failed launch lacks prepared request")
    reception = compute.get("result_reception", {})
    if reception.get("status") == "completed":
        result_path = path.with_name("result.json")
        _, reloaded = read_result(result_path, deadline=deadline, max_bytes=MAX_BYTES)
        _transfer(reception, path=result_path, digest=reloaded["result_sha256"],
                  size=reloaded["bytes_received"], deadline=work_deadline, writer=False)
        _require(compute.get("result_sha256") in {None, reloaded["result_sha256"]}, "failure result hash mismatch")
        result_read = True
    return {"protocol": compute["protocol"], "operation": "score", "status": compute["status"],
            "failure_evidence_verified": True, "execution_started": pid is not None,
            "persistence_ack": persisted, "record_sha256": checkpoint["sha256"] if persisted else None,
            "state_files_reloaded": len(snapshots), "request_reloaded": request_read,
            "result_reloaded": result_read, "cleanup_ack": compute.get("cleanup_ack")}


def validate_score_compute(report: dict[str, Any], *, deadline: float) -> dict[str, Any] | None:
    """Verify a completed score against the exact worker/request/result bytes.

    A zero, explicitly unavailable failure report may have no compute receipt
    because scoring never started. A measured report must carry the receipt.
    """
    _require(_number(deadline), "reload deadline invalid")
    if time.monotonic() >= deadline:
        raise InspectionFailure("infrastructure_error", "EVALUATION_BUDGET_EXHAUSTED",
                                "No compute receipt validation after reload deadline")
    compute = report.get("compute_execution")
    unavailable = (report.get("scoring_failed") is True and report.get("case_pass") is False
                   and report.get("S_core") == 0 and report.get("G") == 0)
    if compute is None and unavailable:
        return None
    _require(isinstance(compute, dict), "execution receipt missing")
    _require(compute.get("protocol") == "l1-compute-v1" and compute.get("operation") == "score",
             "score protocol/operation mismatch")
    if compute.get("status") != "completed" and unavailable:
        return _validate_failed_score(report, compute, deadline=deadline)
    _require(compute.get("status") == "completed" and compute.get("state_history") == STATES,
             "state history is not a completed score chain")
    _require(compute.get("cleanup_ack") is True and compute.get("group_kill_sent") is True
             and compute.get("leader_reaped") is True, "cleanup ACK missing")
    _require(type(compute.get("pid")) is int and compute["pid"] > 0
             and compute.get("process_group") == compute["pid"]
             and type(compute.get("return_code")) is int and compute["return_code"] == 0,
             "process/return code mismatch")
    work_deadline = compute.get("deadline_monotonic")
    _require(_number(work_deadline), "deadline missing")
    path_value = compute.get("record_path")
    _require(isinstance(path_value, str), "worker record path missing")
    record_path = Path(path_value)
    _require(record_path.is_absolute() and record_path.name == "worker_record.json",
             "worker record path invalid")
    session = compute.get("record_persistence")
    _require(isinstance(session, dict) and session.get("protocol") == "l1-json-persistence-session-v1"
             and session.get("deadline_monotonic") == work_deadline
             and session.get("cleanup_deadline_monotonic") is None,
             "persistence session mismatch")
    rows = session.get("records")
    _require(compute.get("state_evidence_protocol") == "l1-compute-state-files-v1",
             "immutable state evidence protocol missing")
    _require(isinstance(rows, list) and len(rows) == 2 * len(STATES), "persistence state ACKs missing")
    previous_finished = None
    for position, row in enumerate(rows):
        state_index, checkpoint = divmod(position, 2)
        path = record_path if checkpoint else record_path.with_name(f"state-{state_index:03d}-{STATES[state_index]}.json")
        mode = "replace_regular" if checkpoint else "create_only"
        _require(isinstance(row, dict) and row.get("protocol") == "l1-json-persistence-v1"
                 and row.get("status") == "completed" and row.get("scope") == "evaluation"
                 and row.get("path") == str(path) and row.get("commit_mode") == mode
                 and row.get("deadline_monotonic") == row.get("evaluation_deadline_monotonic") == work_deadline,
                 "persistence ACK is incomplete or mismatched")
        _transfer(row.get("execution"), path=path, digest=row.get("sha256"),
                  size=row.get("bytes"), deadline=work_deadline, writer=True, commit_mode=mode)
        execution = row["execution"]
        _require(row.get("cleanup_deadline_monotonic") == work_deadline + 2.0
                 and execution.get("cleanup_deadline_monotonic") == row["cleanup_deadline_monotonic"],
                 "persistence cleanup deadline mismatch")
        _require(previous_finished is None or previous_finished <= execution["started_monotonic"],
                 "persistence ACK ordering mismatch")
        previous_finished = execution["finished_monotonic"]
    stored, record_read = read_result(record_path, deadline=deadline, max_bytes=MAX_BYTES)
    _require(record_read["result_sha256"] == rows[-1]["sha256"]
             and record_read["bytes_received"] == rows[-1]["bytes"], "persistence ACK does not bind worker record")
    expected_record = {key: value for key, value in compute.items()
                       if key not in {"record_path", "record_persistence", "record_sha256"}}
    _require(stored == expected_record and compute.get("record_persisted") is True,
             "worker record content mismatch")
    states = []
    for index, state in enumerate(STATES):
        historical, checkpoint = rows[2 * index:2 * index + 2]
        _require(historical["sha256"] == checkpoint["sha256"]
                 and historical["bytes"] == checkpoint["bytes"], "state/checkpoint byte binding mismatch")
        snapshot, reception = read_result(Path(historical["path"]), deadline=deadline, max_bytes=MAX_BYTES)
        _require(reception["result_sha256"] == historical["sha256"]
                 and reception["bytes_received"] == historical["bytes"], "immutable state hash mismatch")
        _require(isinstance(snapshot, dict) and snapshot.get("status") == state
                 and snapshot.get("state_history") == STATES[:index + 1]
                 and snapshot.get("record_persisted") is True, "immutable state content mismatch")
        # Fields once observed cannot silently change between states. Only
        # the explicit state/clock transitions and initial PID/request binding
        # may change; cleanup, request and result receipts remain immutable.
        if states:
            mutable = {"status", "state_history", "state_transition", "budget"}
            if index == 1:
                mutable.add("request_sha256")
            if index == 2:
                mutable.add("pid")
            _require(all(key in snapshot and snapshot[key] == value
                         for key, value in states[-1].items() if key not in mutable),
                     "immutable state observation changed")
        _require(snapshot.get("protocol") == compute["protocol"]
                 and snapshot.get("operation") == "score"
                 and snapshot.get("deadline_monotonic") == work_deadline
                 and snapshot.get("state_evidence_protocol") == compute["state_evidence_protocol"],
                 "immutable state identity mismatch")
        _require(snapshot.get("pid") == (None if index < 2 else compute["pid"])
                 and snapshot.get("request_sha256") == (None if index == 0 else compute["request_sha256"]),
                 "immutable state launch/request mismatch")
        _require(("request_preparation" in snapshot) == (index >= 1)
                 and ("result_reception" in snapshot) == (index == 4)
                 and ("leader_reaped" in snapshot) == (index >= 3),
                 "immutable state phase evidence mismatch")
        states.append(snapshot)
    _require(states[-1] == stored, "immutable terminal state differs from checkpoint")
    budget = compute.get("budget")
    _require(isinstance(budget, dict) and budget.get("protocol") == "l1-deadline-v1"
             and budget.get("deadline_monotonic") == work_deadline and budget.get("exhausted") is False
             and _number(budget.get("remaining_seconds")) and budget["remaining_seconds"] > 0,
             "completed worker budget mismatch")
    if "record_sha256" in compute:
        _require(compute["record_sha256"] == rows[-1]["sha256"], "worker record hash mismatch")

    request_path, result_path = record_path.with_name("request.json"), record_path.with_name("result.json")
    request, request_read = read_result(request_path, deadline=deadline, max_bytes=MAX_BYTES)
    _require(request_read["result_sha256"] == compute.get("request_sha256"), "request hash mismatch")
    _transfer(compute.get("request_preparation"), path=request_path, digest=compute.get("request_sha256"),
              size=request_read["bytes_received"], deadline=work_deadline, writer=True, commit_mode="create_only")
    _require(isinstance(request, dict) and set(request) == {"protocol", "operation", "payload", "deadline"}
             and request["protocol"] == "l1-compute-v1" and request["operation"] == "score"
             and request["deadline"] == work_deadline and isinstance(request["payload"], dict),
             "request envelope mismatch")
    frozen_spec = EvalSpec.from_dict(request["payload"].get("spec", {}))
    _require(frozen_spec.profile == "L1" and frozen_spec.digest == report.get("spec_sha256"),
             "request specification mismatch")
    result, result_read = read_result(result_path, deadline=deadline, max_bytes=MAX_BYTES)
    _require(result_read["result_sha256"] == compute.get("result_sha256"), "result hash mismatch")
    _transfer(compute.get("result_reception"), path=result_path, digest=compute.get("result_sha256"),
              size=result_read["bytes_received"], deadline=work_deadline, writer=False)
    _require(isinstance(result, dict) and set(result) == {"protocol", "operation", "result"}
             and result["protocol"] == "l1-compute-v1" and result["operation"] == "score"
             and isinstance(result["result"], dict), "result envelope mismatch")
    # The parent adds provenance, timings, geometry attachments and error text.
    # A measured score's actual numeric decisions must remain the CPU result.
    if not unavailable and report.get("budget_exhausted") is not True:
        for key in ("spec_sha256", "profile", "mode", "G", "S_core", "S_diagnostic", "S_level",
                    "case_pass", "modules", "gates", "coverage", "task_completion", "declared_checks_pass"):
            _require(key in result["result"] and report.get(key) == result["result"][key],
                     f"result/report {key} mismatch")
        # Optional in older reports; when present it must remain the exact
        # diagnostic that entered the trusted score worker, including failures.
        for key in ('protected_area_diagnostics',):
            if key in result['result'] or key in report:
                _require(key in result['result'] and report.get(key) == result['result'][key],
                         f'result/report {key} mismatch')
    else:
        _require(report.get("case_pass") is False and report.get("S_core") == report.get("G") == 0,
                 "unavailable report retained a successful score")
    return {
        "protocol": compute["protocol"], "operation": "score", "status": "completed",
        "state_history": compute["state_history"], "record_path": str(record_path),
        "record_sha256": rows[-1]["sha256"], "result_sha256": compute["result_sha256"],
        "request_sha256": compute["request_sha256"], "cleanup_ack": True,
        "persistence_ack": True, "request_reloaded": True, "result_reloaded": True,
        "state_files_reloaded": len(states), "immutable_state_history": True,
    }
