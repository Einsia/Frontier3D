"""Unified L1 generation, freeze, rerun, inspection and scoring entry point."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from src.evaluator.l1_budget import BudgetExhausted, DeadlineBudget, positive_seconds
from src.evaluator.l1_compute_receipt import compute_binding, validate_score_compute
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_finalization import load_finalized_report
from src.evaluator.l1_persistence import JsonPersistence
from src.evaluator.l1_result import read_result

from .attempt_log import persistence_scope, write_json_atomic
from .config import load_config
from .configuration import record_binding
from .inspection_publication import validate_reproduction_publication
from .rerun import rerun_submission
from .runner import _task_config_default
from .runner import run as generate

PIPELINE_STATE_PROTOCOL = "l1-pipeline-state-v2"
_STATE_TRANSITIONS: dict[str, set[str]] = {
    "created": {"generation_started"},
    "generation_started": {"generation_completed", "generation_failed"},
    "generation_completed": {"freeze_started"},
    "freeze_started": {"freeze_completed", "freeze_failed"},
    "freeze_completed": {"rerun_started"},
    "rerun_started": {"rerun_completed", "rerun_failed"},
    "rerun_completed": {"inspection_started", "inspection_skipped"},
    "rerun_failed": {"inspection_started", "inspection_skipped"},
    "inspection_started": {"inspection_completed", "inspection_failed"},
    "inspection_completed": {"scoring_started"},
    "inspection_failed": {"scoring_started"},
    "inspection_skipped": {"scoring_skipped"},
    "scoring_started": {"scoring_completed", "scoring_failed"},
    "scoring_completed": {"pipeline_completed", "pipeline_failed"},
    "scoring_skipped": {"pipeline_completed", "pipeline_failed"},
}
_TERMINAL_STATES = {"pipeline_completed", "pipeline_failed", "pipeline_interrupted"}


def _advance_state(history: list[str], next_state: str) -> None:
    """Append a state only when the l1-pipeline state machine permits it."""
    if not history:
        raise RuntimeError("pipeline state history must start with created")
    current = history[-1]
    # Abnormal termination is valid from any nonterminal phase, including
    # errors reading a returned record between two workers.
    if next_state in {"pipeline_failed", "pipeline_interrupted"} and current not in _TERMINAL_STATES:
        history.append(next_state)
        return
    if next_state not in _STATE_TRANSITIONS.get(current, set()):
        raise RuntimeError(
            f"invalid pipeline transition {current!r} -> {next_state!r}"
        )
    history.append(next_state)


PUBLICATION_MAX_BYTES = 64 * 1024 * 1024


class PublicationReadError(ValueError):
    """Stable publication failure retaining the actual reader cleanup receipt."""

    def __init__(self, label: str, failure: InspectionFailure):
        self.code = failure.code
        self.result_reception = getattr(failure, "result_reception", None)
        super().__init__(f"{label} read failed: {failure.code}")


def _read_record(
    path: Path, *, deadline: float, receipts: list | None = None,
    label: str = "publication record",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read and hash the same bytes in a bounded child; never stat in parent.

    Parsing remains cooperative/incremental, not a Python hard-preemption
    guarantee. Every call inherits the phase deadline, including failed reads.
    """
    try:
        value, receipt = read_result(path, deadline=deadline, max_bytes=PUBLICATION_MAX_BYTES)
    except (InspectionFailure, KeyboardInterrupt, SystemExit) as error:
        receipt = getattr(error, "result_reception", None)
        if receipts is not None and isinstance(receipt, dict):
            receipts.append({"label": label, **receipt})
        if isinstance(error, InspectionFailure):
            raise PublicationReadError(label, error) from error
        raise
    if receipts is not None:
        receipts.append({"label": label, **receipt})
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value, receipt


def _validate_compute_execution(
    report: dict[str, Any], *, deadline: float | None = None
) -> dict[str, Any] | None:
    return validate_score_compute(
        report, deadline=deadline if deadline is not None else time.monotonic() + 5.0
    )


def _publication_binding(
    result: dict[str, Any], record_path: Path, *, deadline: float | None = None
) -> dict[str, Any]:
    return _load_publication(result, record_path, deadline=deadline)[0]


def _load_publication(
    result: dict[str, Any], record_path: Path, *, deadline: float | None = None,
    receipts: list | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require a publication index for every returned generation/rerun phase.

    State-machine test adapters obey the same contract as production. Missing
    publication evidence is never a compatibility signal or a successful phase.
    """
    index_value = result.get("record_index")
    if not isinstance(index_value, str) or not index_value:
        raise ValueError("run record index is required")
    # Every read during this publication audit shares one caller allowance.
    deadline = deadline if deadline is not None else time.monotonic() + 5.0
    def read(path, label):
        return _read_record(path, deadline=deadline, receipts=receipts, label=label)

    index_path = Path(index_value).expanduser()
    index, index_read = read(index_path, "run record index")
    if index.get("protocol") != "l1-harness-record-index-v1":
        raise ValueError("run record index protocol mismatch")
    local = Path(index.get("local_record", ""))
    if local != record_path:
        raise ValueError("run record index local record binding mismatch")
    local_record, local_read = read(local, "run local record")
    local_digest = local_read["result_sha256"]
    if index.get("local_record_sha256") != local_digest:
        raise ValueError("run local record hash does not match index")
    trusted_value = index.get("trusted_record")
    trusted_digest = index.get("trusted_record_sha256")
    trusted = None
    if trusted_value is not None:
        trusted = Path(trusted_value)
        _, trusted_read = read(trusted, "run trusted record")
        if trusted_read["result_sha256"] != trusted_digest:
            raise ValueError("run trusted record hash does not match index")
        if result.get("harness_record") is not None and result["harness_record"] != trusted_value:
            raise ValueError("returned trusted record path does not match index")
    binding: dict[str, Any] = {
        "record_index": str(index_path),
        "record_index_sha256": index_read["result_sha256"],
        "local_record": str(local),
        "local_record_sha256": local_digest,
        "trusted_record": str(trusted) if trusted is not None else None,
        "trusted_record_sha256": trusted_digest,
    }
    global_value = result.get("global_index")
    if global_value is not None:
        if not isinstance(global_value, dict):
            raise ValueError("global index receipt must be an object")
        global_path = Path(global_value.get("path", "")).expanduser()
        global_record, global_read = read(global_path, "global index")
        if global_value.get("sha256") != global_read["result_sha256"]:
            raise ValueError("global index receipt hash mismatch")
        if global_record.get("protocol") != "l1-global-record-index-v1":
            raise ValueError("global index protocol mismatch")
        global_payload = global_record.get("record_index")
        if not isinstance(global_payload, dict) or global_payload.get("record_index") != str(index_path):
            raise ValueError("global index local record index binding mismatch")
        if global_payload.get("record_index_sha256") != binding["record_index_sha256"]:
            raise ValueError("global index local record index hash mismatch")
        if index.get("global_index") != str(global_path):
            raise ValueError("local index global shard path mismatch")
        if global_record.get("run_id") != index.get("run_id"):
            raise ValueError("global index run identity mismatch")
        # The shard hash only authenticates its bytes. Its duplicate record
        # pointers, hashes and verdicts must also describe the same revision
        # as the acknowledged local index (including the final scoring write).
        for field in (
            "task_id", "final_status", "local_record", "local_record_sha256",
            "trusted_record", "trusted_record_sha256", "provenance_status",
            "resource_integrity_passed", "not_measurable", "resource_invalidation",
            "report",
        ):
            if global_payload.get(field) != index.get(field):
                raise ValueError(f"global index {field} binding mismatch")
        binding["global_index"] = {
            "path": str(global_path),
            "sha256": global_value["sha256"],
        }
    report_binding = result.get("report_binding")
    if report_binding is None and index.get("report") is not None:
        raise ValueError("returned report binding is missing")
    if report_binding is not None:
        if not isinstance(report_binding, dict):
            raise ValueError("report publication binding must be an object")
        report = Path(report_binding.get("path", "")).expanduser()
        report_digest = report_binding.get("sha256")
        published_report, report_read = read(report, "published report")
        if report_read["result_sha256"] != report_digest:
            raise ValueError("published report hash does not match binding")
        if published_report.get("report_path") not in {None, str(report)}:
            raise ValueError("published report path binding mismatch")
        evidence_value = report_binding.get("evidence")
        if evidence_value is not None:
            if not isinstance(evidence_value, dict):
                raise ValueError("published evidence binding must be an object")
            evidence = Path(evidence_value.get("path", "")).expanduser()
            _, evidence_read = read(evidence, "published evidence")
            if evidence_read["result_sha256"] != evidence_value.get("sha256"):
                raise ValueError("published evidence hash does not match binding")
            evidence_digest = evidence_value.get("sha256")
        else:
            evidence_digest = None
        finalization = report_binding.get("finalization")
        if not isinstance(finalization, dict):
            raise ValueError("published finalization ACK binding is missing")
        if finalization is not None:
            if not isinstance(finalization, dict):
                raise ValueError("published finalization binding must be an object")
            status = finalization.get("status")
            if status not in {"completed", "failed", "interrupted"}:
                raise ValueError("published finalization is not terminal")
            if status == "completed" and (
                finalization.get("report_sha256") != report_digest
                or finalization.get("evidence_sha256") != evidence_digest
            ):
                raise ValueError("published finalization file hashes do not match")
            manifest_value = finalization.get("manifest_path")
            manifest_digest = finalization.get("manifest_sha256")
            if manifest_value is not None:
                manifest = Path(manifest_value).expanduser()
                _, manifest_read = read(manifest, "published finalization manifest")
                if manifest_read["result_sha256"] != manifest_digest:
                    raise ValueError("published finalization manifest hash mismatch")
            # Hashes authenticate bytes, not completion. Every indexed report
            # needs a trusted finalizer ACK; test fixtures use the same rule.
            accepted = local_record.get("evaluation_finalization")
            if not isinstance(accepted, dict):
                raise ValueError("finalized report trusted ACK is missing")
            if any(accepted.get(key) != value for key, value in finalization.items()):
                raise ValueError("finalized report ACK summary mismatch")
            if finalization.get("status") in {
                "completed", "failed", "interrupted"
            }:
                accepted_path = Path(report)
                try:
                    accepted_report = load_finalized_report(
                        accepted_path,
                        accepted,
                        deadline=deadline,
                    )
                except InspectionFailure as error:
                    receipt = getattr(error, "result_reception", None)
                    if receipts is not None and isinstance(receipt, dict):
                        receipts.append({"label": "finalized report ACK reload", **receipt})
                    raise PublicationReadError("finalized report ACK reload", error) from error
                except (OSError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"finalized report ACK reload failed: {type(error).__name__}"
                    ) from error
                if not isinstance(accepted_report, dict):
                    raise ValueError("finalized report ACK reload was not an object")
                compute_receipt = _validate_compute_execution(accepted_report, deadline=deadline)
                expected_compute = (
                    compute_binding(accepted_report["compute_execution"])
                    if accepted_report.get("compute_execution") is not None else None
                )
                if report_binding.get("compute_execution") != expected_compute:
                    raise ValueError("published compute ACK summary mismatch")
                binding["finalization_reload"] = {
                    "status": finalization.get("status"),
                    "accepted": True,
                }
                if compute_receipt is not None:
                    binding["compute_execution"] = compute_receipt
        indexed_report = index.get("report")
        if indexed_report != report_binding:
            raise ValueError("record index report binding mismatch")
        if index.get("final_status") in {"evaluated", "scored", "success"} and (
            published_report.get("scoring_failed") is True
            or published_report.get("budget_exhausted") is True
            or finalization.get("status") != "completed"
        ):
            raise ValueError("successful phase cannot publish an unavailable report")
        binding["report"] = report_binding
    # Missing whole components must not bypass the validations above. Keep
    # these checks after file validation so corrupt artifacts retain precise
    # diagnostics even when another publication component is also missing.
    if trusted is None or not isinstance(result.get("harness_record"), str):
        raise ValueError("run trusted record binding is required")
    if trusted_digest != local_digest:
        raise ValueError("run local/trusted records describe different revisions")
    if global_value is None:
        raise ValueError("run global index binding is required")
    if index.get("final_status") != local_record.get("final_status"):
        raise ValueError("run record/index final status mismatch")
    if result.get("final_status") != index.get("final_status"):
        raise ValueError("returned final status does not match index")
    if result.get("report") is not None or result.get("report_path") is not None:
        if report_binding is None:
            raise ValueError("returned report requires a publication binding")
        if result.get("report_path") not in {None, report_binding["path"]}:
            raise ValueError("returned report path does not match binding")
    if 'seed_runs' in local_record or 'reproduction_consistency' in local_record:
        inspection_proof = validate_reproduction_publication(
            local_record, record_path.parent, deadline=deadline, receipts=receipts,
        )
        # Stable byte bindings belong here; actual read PIDs/times belong in
        # publication_reads so independent reloads do not change identity.
        binding['reproduction_inspections'] = {
            'protocol': inspection_proof['protocol'], 'status': inspection_proof['status'],
            'verified_count': inspection_proof['verified_count'],
            'unavailable_count': inspection_proof['unavailable_count'],
            'observations': {path: {key: row[key] for key in
                                   ('status', 'record_path', 'record_sha256', 'facts_sha256', 'metadata_ack')
                                   if key in row}
                             for path, row in inspection_proof['observations'].items()},
        }
    return binding, local_record


def run_pipeline(
    task_id: str,
    tasks_root: Path,
    config_path: Path,
    output_dir: Path,
    *,
    env_file: Path | None = None,
    trial_id: str = "0",
    blender: Path | None = None,
    timeout: float | None = None,
    evaluate: bool = True,
) -> dict[str, Any]:
    """Run single-shot generation with durable, observed phase checkpoints.

    Freeze completion comes from the rerunner after it stages the snapshot;
    inspection/scoring completion comes from the evaluator, not return-value
    guesses. A report may be diagnostic on a failed run. Forced termination
    can leave a nonterminal checkpoint; that is never treated as success.
    """
    started = time.monotonic()
    if not isinstance(task_id, str) or not re.fullmatch(r"L1/[A-Za-z0-9_-]+", task_id):
        raise ValueError("pipeline task_id must be an L1 task identifier")
    if not isinstance(trial_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", trial_id):
        raise ValueError("pipeline trial_id must be a safe identifier")
    output_dir = output_dir.expanduser().resolve()
    pipeline_id = f"{task_id.replace('/', '__')}__trial-{trial_id}__{time.time_ns()}"
    pipeline_dir = output_dir / "pipelines" / pipeline_id
    pipeline_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = pipeline_dir / "pipeline_manifest.json"
    budget: DeadlineBudget | None = None
    state_history = ["created"]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "protocol": "l1-pipeline-v1",
        "pipeline_id": pipeline_id,
        "task_id": task_id,
        "trial_id": trial_id,
        "config_path": str(config_path.expanduser().resolve()),
        "phases": {phase: "not_started" for phase in ("generation", "freeze", "rerun", "inspection", "scoring")},
        "state_protocol": PIPELINE_STATE_PROTOCOL,
        "state_history": state_history,
        "events": [],
        "seed_runs": {},
        "process_id": os.getpid(),
        "started_at_ns": time.time_ns(),
        "final_status": "running",
    }
    result: dict[str, Any] = {
        "pipeline_dir": str(pipeline_dir),
        "pipeline_manifest": str(manifest_path),
    }
    active_phase = "generation"
    persistence: JsonPersistence | None = None

    def checkpoint() -> None:
        manifest["updated_at_ns"] = time.time_ns()
        manifest["elapsed_seconds"] = time.monotonic() - started
        if budget is not None and persistence is not None:
            manifest["budget"] = budget.record("pipeline")
            manifest["record_persistence"] = persistence.evidence()
            if state_history[-1] in {"pipeline_failed", "pipeline_interrupted"}:
                # Failure publication has one nonrenewable allowance. Do not
                # attempt a normal write after the reader consumed the budget.
                persistence.write(manifest_path, manifest, cleanup=True)
                return
            try:
                with persistence_scope(persistence):
                    write_json_atomic(manifest_path, manifest)
            except BaseException as error:
                # One non-renewable cleanup allowance may publish the failed
                # checkpoint. Never turn a failed write into a success receipt.
                manifest["record_persistence_failure"] = type(error).__name__
                # Do not retry a success-shaped payload using the failure
                # allowance. The outer handler constructs the failed terminal
                # record and alone owns its bounded cleanup publication.
                persistence.begin_cleanup()
                raise
        else:
            write_json_atomic(manifest_path, manifest)

    def event(phase: str, status: str, details: dict[str, Any]) -> None:
        nonlocal active_phase
        if phase == "baseline":
            if state_history[-1] != "rerun_started":
                raise RuntimeError("baseline event outside the rerun phase")
            manifest.setdefault("phase_evidence", {})["baseline"] = details
        elif phase == "seed":
            if state_history[-1] != "rerun_started":
                raise RuntimeError("seed event outside the rerun phase")
            manifest["seed_runs"][str(details["seed"])] = details
        else:
            _advance_state(state_history, f"{phase}_{status}")
            manifest["phases"][phase] = status
            if status == "started":
                active_phase = phase
            manifest.setdefault("phase_evidence", {})[phase] = details
        manifest["events"].append({
            "sequence": len(manifest["events"]),
            "phase": phase, "status": status,
            "elapsed_seconds": time.monotonic() - started,
            "details": details,
        })
        checkpoint()

    def finish(status: str, terminal: str) -> dict[str, Any]:
        _advance_state(state_history, terminal)
        manifest["final_status"] = status
        manifest["finished_at_ns"] = time.time_ns()
        result["final_status"] = status
        try:
            checkpoint()
        except BaseException:
            if terminal == "pipeline_completed":
                # A noncommitted terminal checkpoint cannot stop the outer
                # exception handler from recording the real failure.
                state_history.pop()
                manifest["final_status"] = "running"
                result.pop("final_status", None)
            raise
        return result

    checkpoint()
    try:
        config = load_config(config_path)
        if config.task_id != task_id:
            raise ValueError("Pipeline configuration task_id mismatch")
        if timeout is not None:
            positive_seconds(timeout, "timeout")
        budget = DeadlineBudget.start(config.max_total_seconds, started=started)
        persistence = JsonPersistence(budget.deadline)
        manifest["harness_config_sha256"] = config.digest
        manifest["configuration"] = {
            "config_effective_sha256": config.effective_digest, "config_file_sha256": config.file_sha256,
            "effective": config.effective(), "config_path": config.source_path,
        }
        budget.check()
        event("generation", "started", {})
        generation = generate(
            task_id, tasks_root, config_path, output_dir, env_file,
            trial_id, blender, execute=False, deadline=budget.deadline,
            expected_binding=manifest["configuration"],
        )
        result["generation"] = generation
        generation_record_path = Path(
            generation.get("run_harness_record", generation["harness_record"])
        )
        generation_reads = manifest.setdefault("publication_reads", {}).setdefault("generation", [])
        generation_publication, generation_record = _load_publication(
            generation, generation_record_path, deadline=budget.deadline, receipts=generation_reads,
        )
        manifest["configuration"] = record_binding(generation_record, manifest["configuration"])
        manifest["generation"] = {
            "run_dir": generation["run_dir"], "record": str(generation_record_path),
            "status": generation.get("final_status"),
            "record_sha256": generation_publication["local_record_sha256"],
            "publication": generation_publication,
        }
        budget.check()
        if generation.get("final_status") not in {"generated", "success"}:
            event("generation", "failed", manifest["generation"])
            return finish("generation_failed", "pipeline_failed")
        event("generation", "completed", manifest["generation"])
        event("freeze", "started", {"source": generation["run_dir"]})
        rerun = rerun_submission(
            task_id, tasks_root, config_path, Path(generation["run_dir"]), output_dir,
            trial_id=f"{trial_id}-rerun", blender=blender, timeout=timeout,
            evaluate=evaluate, on_phase=event, deadline=budget.deadline,
            expected_binding=manifest["configuration"],
        )
        result["rerun"] = rerun
        active_phase = "finalization"
        rerun_record_path = Path(rerun.get("run_harness_record", rerun["harness_record"]))
        rerun_reads = manifest.setdefault("publication_reads", {}).setdefault("rerun", [])
        rerun_publication, rerun_record = _load_publication(
            rerun, rerun_record_path, deadline=budget.deadline, receipts=rerun_reads,
        )
        record_binding(rerun_record, manifest["configuration"])
        manifest["rerun"] = {
            "run_dir": rerun["run_dir"], "record": str(rerun_record_path),
            "status": rerun.get("final_status"),
            "record_sha256": rerun_publication["local_record_sha256"], "report": rerun.get("report_path"),
            "publication": rerun_publication,
        }
        budget.check()
        if state_history[-1] not in {"scoring_completed", "scoring_skipped", "scoring_failed"}:
            raise RuntimeError("rerunner did not report all pipeline phase transitions")
        phases = manifest["phases"]
        succeeded = (
            rerun.get("final_status") in {"evaluated", "success", "scored"}
            and phases["rerun"] == "completed"
            and (
                phases["inspection"] == phases["scoring"] == "completed"
                if evaluate
                else phases["inspection"] == phases["scoring"] == "skipped"
            )
        )
        if succeeded:
            return finish("scored" if evaluate else "evaluated", "pipeline_completed")
        status = rerun.get("final_status", "rerun_failed")
        if status in {"evaluated", "success", "scored"}:
            status = "scoring_failed" if phases["scoring"] == "failed" else "inspection_failed" if phases["inspection"] == "failed" else "phase_incomplete"
        return finish(status, "pipeline_failed")
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        interrupted = isinstance(error, (KeyboardInterrupt, SystemExit))
        inspection_proof = getattr(error, 'reproduction_publication', None)
        if isinstance(inspection_proof, dict):
            manifest['reproduction_publication_failure'] = inspection_proof
            result['reproduction_publication_failure'] = inspection_proof
        exhausted = isinstance(error, BudgetExhausted) or getattr(error, "code", None) == "EVALUATION_BUDGET_EXHAUSTED"
        manifest["failure"] = {
            "phase": active_phase,
            "code": "PIPELINE_INTERRUPTED" if interrupted else
            "PIPELINE_BUDGET_EXHAUSTED" if exhausted else "PIPELINE_STAGE_ERROR",
            "exception_type": type(error).__name__,
            # Exception strings can contain credentials from model services;
            # phase-local logs, not this shared manifest, own those details.
        }
        publication = getattr(error, "l1_failure_publication", None)
        if isinstance(publication, dict):
            # Keep only trusted paths/receipts returned by the append-only
            # failure publisher. Never copy exception text or arbitrary error
            # attributes into the pipeline manifest.
            binding = {
                key: publication.get(key)
                for key in (
                    "failure_id",
                    "final_status",
                    "harness_record",
                    "run_harness_record",
                    "record_index",
                    "global_index",
                    "global_index_failure",
                    "launcher_io",
                    "sandbox_io",
                    "inspector_execution",
                    "inspector_persistence",
                    "reproduction_inspections",
                    "launcher_discovery",
                    "failure_publication_errors",
                )
                if key in publication
            }
            manifest["failure_publication"] = binding
            result["failure_publication"] = binding
        if active_phase in manifest["phases"] and state_history[-1] == f"{active_phase}_started":
            # Assemble one terminal failure checkpoint instead of spending
            # the cleanup allowance on an intermediate expired normal write.
            _advance_state(state_history, f"{active_phase}_failed")
            manifest["phases"][active_phase] = "failed"
            manifest.setdefault("phase_evidence", {})[active_phase] = manifest["failure"]
            manifest["events"].append({
                "sequence": len(manifest["events"]), "phase": active_phase,
                "status": "failed", "elapsed_seconds": time.monotonic() - started,
                "details": manifest["failure"],
            })
        try:
            finish(
                "interrupted" if interrupted else
                "budget_exhausted" if exhausted else f"{active_phase}_failed",
                "pipeline_interrupted" if interrupted else "pipeline_failed",
            )
        except (OSError, TypeError, ValueError, RuntimeError, KeyboardInterrupt, SystemExit) as cleanup_error:
            # Preserve the original failure even if no durable write remains
            # possible. The last on-disk checkpoint is not a success ACK.
            result["checkpoint_failure"] = {
                "exception_type": type(cleanup_error).__name__,
                "code": getattr(cleanup_error, "code", None),
            }
            result["failure"] = manifest["failure"]
        if interrupted:
            raise
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the unified L1 generation/rerun pipeline"
    )
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--harness-config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--trial-id", default="0")
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--no-evaluate", action="store_true")
    args = parser.parse_args()
    try:
        tasks_root = args.tasks_root.expanduser().resolve()
        config_path = args.harness_config or _task_config_default(args.task, tasks_root)
        result = run_pipeline(
            args.task,
            tasks_root,
            config_path.expanduser().resolve(),
            args.output_dir,
            env_file=args.env_file,
            trial_id=args.trial_id,
            blender=args.blender,
            timeout=args.timeout,
            evaluate=not args.no_evaluate,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"[l1-pipeline] error: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final_status"] in {"scored", "evaluated"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
