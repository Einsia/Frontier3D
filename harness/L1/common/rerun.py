"""Fixed-seed rerun and evaluation orchestration for an existing L1 submission."""

from __future__ import annotations

import argparse
import copy
import inspect
import json
import os
import platform
import shutil
import time
from collections.abc import Callable
from contextlib import nullcontext
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.evaluator.l1_budget import DeadlineBudget, positive_seconds
from src.evaluator.l1_compute_receipt import compute_binding
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_log_io import write_bounded_log
from src.evaluator.l1_parent_io import (
    audit_directory,
    copy_regular_files,
    ensure_directory,
    resolve_executable,
)
from src.evaluator.l1_persistence import JsonPersistence
from src.evaluator.l1_runner import evaluate_l1_submission
from src.evaluator.spec import EVALUATOR_VERSION
from src.generator.task_adapter import load_benchmark_task

from .attempt_log import (
    persistence_scope,
    sha256,
    sha256_bytes,
    write_json,
    write_json_atomic,
)
from .blender_executor import Execution, run_blender
from .codex_invoker import DEFAULT_WORKSPACE_LIMITS
from .config import HarnessConfig, load_config
from .configuration import configuration_snapshot, save_configuration
from .costs import refresh_unknown_costs
from .execution_provenance import bind_execution, validate_repair_round
from .failure_record import publish_failure_records
from .global_index import latest_write_receipt, publish_global_index
from .reproduction import compare_seed_artifacts
from .resource_invalidation import recommit_resource_failure
from .resources import (
    bound_comparison_intact,
    comparison_binding,
    declared_authority,
    freeze_comparison_artifacts,
    generated_authority,
)
from .rng_evidence import summarize_rng_evidence
from .runner import _task_config_default, _task_spec
from .submission import stage_submission

_RERUN_FAILURE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "l1_rerun_failure_context", default=None
)


def _resolve_blender_entrypoint(
    requested: str, *, deadline: float, phase: str, receipts: list[dict],
    expected: dict | None = None,
) -> tuple[Path, dict]:
    """Resolve under the existing rerun budget, preserving failure provenance.

    A second observation catches observed replacement between phases; neither
    observation pins an executable or its interpreter/dependencies for exec.
    """
    try:
        receipt = resolve_executable(requested, deadline=deadline)
    except BaseException as error:
        observed = getattr(error, "parent_io", {
            "status": "not_started", "requested": requested, "pid": None,
        })
        receipts.append({"phase": phase, "observation": observed, "accepted": False})
        error.launcher_io = observed
        raise
    unchanged = expected is None or receipt["result"] == expected["result"]
    receipts.append({"phase": phase, "observation": receipt, "accepted": unchanged})
    if not unchanged:
        error = InspectionFailure("infrastructure_error", "BLENDER_LAUNCHER_CHANGED",
                                  "Blender launcher observation changed between rerun phases")
        error.launcher_io = receipt
        raise error
    return Path(receipt["result"]["path"]), receipt


def _materialize_legacy_aliases(
    root: Path, required: tuple[str, ...], *, deadline: float | None = None
) -> list[dict[str, Any]]:
    """Normalize historical ``assembled.glb`` output to the frozen scene.glb name."""

    aliases: list[dict[str, Any]] = []
    if "scene.glb" in required:
        target = root / "scene.glb"
        for legacy in (root / "assembled.glb", root / "assembly.glb"):
            if not target.exists() and legacy.is_file() and not legacy.is_symlink():
                if deadline is None:
                    shutil.copy2(legacy, target)
                    path_io = None
                else:
                    path_io = copy_regular_files(
                        root,
                        root,
                        (legacy.name,),
                        target_files=(target.name,),
                        deadline=deadline,
                    )["execution"]
                alias = {"source": legacy.name, "target": target.name}
                if path_io is not None:
                    alias["path_io"] = path_io
                aliases.append(alias)
                break
    return aliases


def _artifact_state(
    root: Path, required: tuple[str, ...]
) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for name in required:
        path = root / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size > 0:
            hashes[name] = sha256(path)
        else:
            missing.append(name)
    return hashes, missing


def _audit(
    root: Path,
    required: tuple[str, ...],
    hashes: dict[str, str],
    submission: dict[str, Any],
) -> dict[str, Any]:
    """Perform the provenance/immutability checks available before evaluator inspection."""

    failures: list[str] = []
    for name in required:
        path = root / name
        if not path.is_file() or path.is_symlink():
            failures.append(f"{name}: missing or symlink")
            continue
        if hashes.get(name) != sha256(path):
            failures.append(f"{name}: hash changed")
    for relative, expected in submission.get("files", {}).items():
        path = root.joinpath(*Path(relative).parts)
        if not path.is_file() or path.is_symlink():
            failures.append(f"submission {relative}: missing or symlink")
        elif expected.get("sha256") != sha256(path):
            failures.append(f"submission {relative}: hash changed")
    canonical = root / submission.get("canonical_entrypoint", "solution.py")
    if not canonical.is_file() or canonical.is_symlink():
        failures.append("canonical solution.py: missing or symlink")
    elif submission.get("canonical_sha256") != sha256(canonical):
        failures.append("canonical solution.py: hash changed")
    return {
        "version": "l1-basic-integrity-v1",
        "passed": not failures,
        "failures": failures,
        "scope": [
            "required artifacts are regular non-symlink files",
            "artifact hashes are stable after seed execution",
            "declared submission files are regular non-symlink files",
        ],
        "limitations": [
            "This is provenance and immutability auditing, not a complete anti-cheating proof.",
            "Reference leakage and billboard detection remain evaluator-side checks.",
        ],
    }


def _execution_record(
    execution: Execution, log_io: dict[str, Any] | None = None
) -> dict[str, Any]:
    record = {
        "status": execution.status,
        "error_code": execution.error_code,
        "return_code": execution.return_code,
        "elapsed_seconds": execution.elapsed_seconds,
        "sandbox_status": execution.sandbox_status,
        "resource_limits": execution.resource_limits,
        "rng_trace": execution.rng_trace,
        "workspace_guard": execution.workspace_guard,
        "launcher_io": execution.launcher_io,
        "sandbox_io": execution.sandbox_io,
    }
    if log_io is not None:
        record["log_io"] = log_io
    return record


def _run_candidate_blender(
    script: Path,
    output: Path,
    workspace: Path,
    timeout: float,
    blender: Path | None,
    *,
    extra_env: dict[str, str] | None = None,
    deadline: float,
) -> Execution:
    """Run Blender with quota policy while retaining legacy test adapters."""
    kwargs: dict[str, Any] = {
        "extra_env": extra_env,
        "deadline": deadline,
    }
    try:
        parameters = inspect.signature(run_blender).parameters.values()
        accepts_limits = any(
            parameter.name == "workspace_limits"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except (TypeError, ValueError):
        accepts_limits = True
    if accepts_limits:
        kwargs["workspace_limits"] = DEFAULT_WORKSPACE_LIMITS
    return run_blender(script, output, workspace, timeout, blender, **kwargs)


def _freeze_original_artifacts(
    source_root: Path,
    snapshot_root: Path,
    required: tuple[str, ...],
    *,
    deadline: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Copy pre-existing candidate outputs outside executable workspaces."""
    frozen: dict[str, dict[str, Any]] = {}
    original_root = snapshot_root / "original_artifacts"
    names = []
    for name in required:
        source = source_root / name
        if not source.is_file() or source.is_symlink() or source.stat().st_size == 0:
            continue
        names.append(name)
    if not names:
        return frozen
    if deadline is None:
        original_root.mkdir(parents=True, exist_ok=True)
        for name in names:
            target = original_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_root / name, target)
            frozen[name] = {"sha256": sha256(target), "bytes": target.stat().st_size}
        return frozen
    ensure_directory(original_root, deadline=deadline, parents=True)
    receipt = copy_regular_files(
        source_root,
        original_root,
        tuple(names),
        deadline=deadline,
    )
    by_path = {row["path"]: row for row in receipt["result"]["files"]}
    for name in names:
        row = by_path[name]
        frozen[name] = {
            "sha256": row["sha256"],
            "bytes": row["bytes"],
            "path_io": receipt["execution"],
        }
    return frozen


def _baseline_binding(baseline: dict[str, Any]) -> dict[str, Any]:
    return {key: baseline[key] for key in (
        "protocol", "origin", "program_seed", "source_snapshot_digest", "artifact_sha256", "record_path",
        "resource_binding", "record_sha256", "trial_id", "repair_round", "execution_binding",
    )}


def _baseline_intact(baseline: dict[str, Any]) -> bool:
    """Normal drift detection; containment is still the executor's responsibility."""
    try:
        return (baseline["status"] == "ready"
                and not Path(baseline["record_path"]).is_symlink()
                and sha256(Path(baseline["record_path"])) == baseline["record_sha256"]) and all(
            Path(baseline["artifacts"][name]).is_file()
            and not Path(baseline["artifacts"][name]).is_symlink()
            and sha256(Path(baseline["artifacts"][name])) == digest
            for name, digest in baseline["artifact_sha256"].items()
        ) and set(baseline["artifact_sha256"]) == {"scene.blend", "scene.glb"} and bound_comparison_intact(
            baseline["resources"], baseline["resource_binding"]
        )
    except (OSError, KeyError, TypeError, ValueError):
        return False


def _report_binding(report: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a reloadable binding for the final evaluator report."""
    if not isinstance(report, dict):
        return None
    value = report.get("report_path")
    if not isinstance(value, str):
        return None
    path = Path(value)
    binding: dict[str, Any] = {
        "path": str(path),
        "status": report.get("status"),
        "case_pass": report.get("case_pass"),
        "resource_integrity_passed": report.get("resource_integrity_passed"),
        "provenance_status": report.get("provenance_status"),
    }
    finalization = report.get("finalization")
    # Declared transactions bind accepted bytes without touching their paths.
    # In particular failure cleanup must not block on an overwritten report.
    binding["sha256"] = None if isinstance(finalization, dict) else (
        sha256(path) if path.is_file() and not path.is_symlink() else None
    )
    evidence = report.get("evidence_path")
    if isinstance(evidence, str):
        evidence_path = Path(evidence)
        binding["evidence"] = {
            "path": str(evidence_path),
            "sha256": None if isinstance(finalization, dict) else (
                sha256(evidence_path)
                if evidence_path.is_file() and not evidence_path.is_symlink()
                else None
            ),
        }
    if isinstance(finalization, dict):
        binding["finalization"] = {
            key: finalization.get(key)
            for key in (
                "protocol",
                "status",
                "manifest_path",
                "manifest_sha256",
                "report_sha256",
                "evidence_sha256",
            )
            if key in finalization
        }
        if finalization.get("status") == "completed":
            # Accepted hashes describe committed bytes, not whatever happens
            # to occupy the paths when the caller builds its index.
            binding["sha256"] = finalization.get("report_sha256")
            if isinstance(evidence, str):
                binding["evidence"] = {
                    "path": evidence, "sha256": finalization.get("evidence_sha256"),
                }
        elif finalization.get("status") in {"failed", "interrupted"}:
            # Failure cleanup prioritizes the zero-score report; evidence and
            # manifest may never have been committed. Do not bind stale files
            # from a previous success, or require missing optional files.
            persistence = finalization.get("persistence")
            rows = persistence.get("records", []) if isinstance(persistence, dict) else []
            rows = rows if isinstance(rows, list) else []

            def latest_ack(target):
                matches = [row for row in rows if isinstance(row, dict) and row.get("path") == target]
                latest = matches[-1] if matches else None
                return latest if latest and latest.get("status") == "completed" else None

            report_ack = latest_ack(str(path))
            binding["sha256"] = report_ack.get("sha256") if report_ack else None
            binding.pop("evidence", None)
            evidence_ack = latest_ack(evidence) if isinstance(evidence, str) else None
            if evidence_ack is not None:
                binding["evidence"] = {"path": evidence, "sha256": evidence_ack.get("sha256")}
            # The trusted failure ACK reloads only the acknowledged report.
            # A leftover manifest is not a success or a failure commit ACK.
            binding["finalization"] = {
                "protocol": finalization.get("protocol"), "status": finalization["status"],
            }
    compute = report.get("compute_execution")
    if isinstance(compute, dict):
        binding["compute_execution"] = compute_binding(compute)
    return binding


def _prepare_baseline(
    *, task, spec, config, source_root: Path, snapshot_root: Path, run_dir: Path,
    source_digest: str, submission_metadata: dict[str, Any], original_artifacts: dict,
    budget: DeadlineBudget, timeout: float, blender: Path | None, resource_blender: Path, on_phase=None,
    trial_id: str = "rerun", repair_round: int = 0,
    persist_checkpoint: Callable[[Path, Any], None] | None = None,
    persistence: JsonPersistence | None = None,
) -> dict[str, Any]:
    """Freeze provided scenes, or execute one predetermined independent baseline.

    Never replace an incomplete supplied delivery or a failed generated baseline
    with one of the later successful seeds. Both the baseline and seed zero are
    separate executions, and no reference answer is available through this API.
    """
    started = time.monotonic()
    root = run_dir / "reconstruction_baseline"
    path_receipt = ensure_directory(root, deadline=budget.deadline, parents=True)
    names = ("scene.blend", "scene.glb")
    provided = any((source_root / name).exists() or (source_root / name).is_symlink() for name in names)
    baseline = {
        "protocol": "l1-reconstruction-baseline-v1", "task_id": task.task_id,
        "origin": "provided_artifacts" if provided else "independent_execution",
        "program_seed": None if provided else spec.seeds[0],
        "trial_id": trial_id, "repair_round": repair_round,
        "source_snapshot_digest": source_digest, "spec_sha256": spec.digest,
        "run_id": run_dir.name,
        "configuration_record": str(run_dir / "configuration/configuration.json"),
        "configuration_sha256": sha256(run_dir / "configuration/configuration.json"),
        "record_path": str(root / "record.json"), "status": "started",
        "artifacts": {}, "artifact_sha256": {}, "execution_attempted": False,
        "execution_seconds": 0.0, "cost_seconds": 0.0,
        "resources": None, "resource_binding": None, "comparison_artifacts": {},
        "path_io": [path_receipt["execution"]],
        "log_io": {},
        "policy": "fixed_first_spec_seed_no_retry_no_seed_substitution",
        "execution_binding": bind_execution(task_id=task.task_id, trial_id=trial_id, repair_round=repair_round,
                                            program_seed=None if provided else spec.seeds[0], source_digest=source_digest,
                                            execution=None, artifacts={}),
    }

    def checkpoint(status):
        baseline["status"] = status
        baseline["cost_seconds"] = time.monotonic() - started
        baseline["budget"] = budget.record("reconstruction_baseline")
        if persist_checkpoint is None:
            write_json_atomic(root / "record.json", baseline)
        else:
            persist_checkpoint(root / "record.json", baseline)
        if on_phase is not None:
            on_phase("baseline", status, copy.deepcopy(baseline))

    def freeze_resources(authority):
        checkpoint("freezing_resources")
        with persistence_scope(persistence) if persistence is not None else nullcontext():
            resources = freeze_comparison_artifacts(
                blender=resource_blender, artifacts=baseline["artifacts"],
                output=run_dir / "resource_snapshots/baseline", authority=authority,
                task_id=task.task_id, timeout=timeout, deadline=budget.deadline,
            )
        baseline["resources"] = resources
        baseline["resource_binding"] = comparison_binding(resources)
        if resources["status"] == "ready" and bound_comparison_intact(resources, baseline["resource_binding"]):
            baseline["comparison_artifacts"] = dict(resources["artifacts"])
            checkpoint("budget_exhausted" if budget.exhausted else "ready")
        else:
            baseline["failure"] = resources.get("failure", {"reason": "Resource snapshot unavailable or changed"})
            checkpoint("budget_exhausted" if budget.exhausted or resources["status"] == "budget_exhausted" else "failed")

    checkpoint("started")
    try:
        if provided:
            for name in names:
                if name in original_artifacts:
                    baseline["artifacts"][name] = str(snapshot_root / "original_artifacts" / name)
                    baseline["artifact_sha256"][name] = original_artifacts[name]["sha256"]
            baseline["missing_artifacts"] = [name for name in names if name not in baseline["artifacts"]]
            baseline["execution_binding"]["artifact_sha256"] = dict(baseline["artifact_sha256"])
            if budget.exhausted or baseline["missing_artifacts"]:
                checkpoint("budget_exhausted" if budget.exhausted else "failed")
            else:
                freeze_resources(declared_authority(source_root=source_root, snapshot_root=snapshot_root,
                                                    metadata=submission_metadata))
            return baseline

        workspace = root / "workspace"
        workspace_path_receipt = ensure_directory(workspace, deadline=budget.deadline, parents=False)
        baseline["path_io"].append(workspace_path_receipt["execution"])
        baseline["workspace"] = str(workspace)
        if not budget.exhausted:
            task.stage_environment(workspace)
        if not budget.exhausted:
            stage_submission(snapshot_root, workspace, reserved_outputs=spec.required_artifacts,
                             entrypoint_policy=config.entrypoint_policy, deadline=budget.deadline)
        if budget.exhausted:
            checkpoint("budget_exhausted")
            return baseline
        workspace_before_receipt = audit_directory(workspace, deadline=budget.deadline)
        baseline["path_io"].append(workspace_before_receipt["execution"])
        baseline["workspace_io_before"] = workspace_before_receipt["result"]
        baseline["execution_attempted"] = True
        baseline["execution_seconds"] = None  # Unknown until the executor returns.
        # Persist the launch decision before handing control to the candidate.
        checkpoint("running")
        seed = str(spec.seeds[0])
        execution = _run_candidate_blender(
            workspace / "solution.py", workspace / "scene.blend", workspace, timeout, blender,
            extra_env={"THREEDBENCH_SEED": seed, "BENCHMARK_SEED": seed, "PYTHONHASHSEED": seed,
                       "THREEDBENCH_REPAIR_ROUND": str(repair_round)},
            deadline=budget.deadline,
        )
        baseline["execution"] = _execution_record(execution)
        baseline["log_io"] = {
            "stdout": write_bounded_log(
                workspace / "blender.stdout.log", execution.stdout,
                deadline=budget.deadline,
            ),
            "stderr": write_bounded_log(
                workspace / "blender.stderr.log", execution.stderr,
                deadline=budget.deadline,
            ),
        }
        if not budget.exhausted:
            workspace_after_receipt = audit_directory(workspace, deadline=budget.deadline)
            baseline["path_io"].append(workspace_after_receipt["execution"])
            baseline["workspace_io_after"] = workspace_after_receipt["result"]
        baseline["execution_binding"] = bind_execution(
            task_id=task.task_id, trial_id=trial_id, repair_round=repair_round, program_seed=spec.seeds[0],
            source_digest=source_digest, execution=execution, artifacts={},
        )
        baseline["execution_seconds"] = execution.elapsed_seconds
        if budget.exhausted:
            checkpoint("budget_exhausted")
            return baseline
        baseline["aliases"] = _materialize_legacy_aliases(
            workspace, spec.required_artifacts, deadline=budget.deadline
        )
        hashes, missing = _artifact_state(workspace, spec.required_artifacts)
        baseline["execution_binding"]["artifact_sha256"] = dict(hashes)
        baseline["missing_artifacts"] = missing
        baseline["integrity"] = _audit(workspace, spec.required_artifacts, hashes, submission_metadata)
        if execution.status != "success" or missing or not baseline["integrity"]["passed"]:
            checkpoint("failed")
            return baseline
        frozen = root / "artifacts"
        frozen_path_receipt = ensure_directory(frozen, deadline=budget.deadline, parents=False)
        baseline["path_io"].append(frozen_path_receipt["execution"])
        frozen_copy_receipt = copy_regular_files(
            workspace,
            frozen,
            names,
            deadline=budget.deadline,
        )
        baseline["path_io"].append(frozen_copy_receipt["execution"])
        for row in frozen_copy_receipt["result"]["files"]:
            name = row["path"]
            if row["sha256"] != hashes[name]:
                raise ValueError("Baseline artifact changed during freezing")
            baseline["artifacts"][name] = str(frozen / name)
            baseline["artifact_sha256"][name] = hashes[name]
        if budget.exhausted:
            checkpoint("budget_exhausted")
        else:
            freeze_resources(generated_authority(workspace))
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        baseline["failure"] = {"exception_type": type(error).__name__, "reason": str(error)}
        checkpoint("interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed")
        raise
    return baseline


def _refresh_resource_integrity(record, run_dir, budget):
    """Recheck after callbacks/evaluation; never retain a pass after drift."""
    if budget.exhausted:
        return False  # No candidate-sized parent I/O after the shared cutoff.
    baseline_ok = _baseline_intact(record["reconstruction_baseline"])
    source_ok = _audit(Path(record["source_snapshot"]["path"]), (), {}, record["submission"])["passed"]
    resources_ok = True
    for seed, item in record["seed_runs"].items():
        snapshot = record["resource_snapshots"]["per_seed"].get(seed)
        intact = bool(snapshot and bound_comparison_intact(snapshot, item["resource_binding"]))
        item["resource_integrity_passed"] = intact
        resources_ok = resources_ok and intact
        if not intact or not baseline_ok or not source_ok:
            semantic = record["reproduction_consistency"]["per_seed"][seed]
            if semantic["status"] in {"ok", "failed"}:
                semantic.update(status="not_measurable", reason="Bound source/baseline/resource evidence unavailable or changed")
                item["reproduction_status"] = "not_measurable"
    canonical = record["canonical_derivation"]
    hashes, _ = _artifact_state(run_dir, ("scene.blend", "scene.glb"))
    canonical_ok = bool(canonical and hashes == canonical["artifact_sha256"])
    record["baseline_integrity_passed"] = baseline_ok
    record["resource_integrity_passed"] = baseline_ok and resources_ok and canonical_ok and source_ok
    summary = record["reproduction_consistency"]
    summary["passed_count"] = sum(item["status"] == "ok" for item in summary["per_seed"].values())
    summary["measured_count"] = sum(item["status"] in {"ok", "failed"} for item in summary["per_seed"].values())
    if baseline_ok and resources_ok and canonical_ok and source_ok:
        record["provenance_status"] = "verified"
        record["not_measurable"] = False
        return True
    summary.update(status="not_measurable", reason="Bound source/baseline/resource evidence unavailable or changed")
    record["integrity_passed"] = record["integrity"]["passed"] = False
    failed_components = []
    if not baseline_ok:
        failed_components.append("reconstruction_baseline")
    if not resources_ok:
        failed_components.append("resource_snapshots")
    if not canonical_ok:
        failed_components.append("canonical_derivation")
    if not source_ok:
        failed_components.append("source_snapshot")
    record["provenance_status"] = "unverified"
    record["not_measurable"] = True
    record["resource_invalidation"] = {
        "protocol": "l1-resource-invalidation-v1",
        "status": "not_measurable",
        "reason": "Bound source/baseline/resource evidence unavailable or changed",
        "components": failed_components,
        "baseline_integrity_passed": baseline_ok,
        "resource_integrity_passed": resources_ok,
        "canonical_integrity_passed": canonical_ok,
        "source_integrity_passed": source_ok,
    }
    reason = "final source/baseline/resource/canonical audit failed"
    if reason not in record["integrity"]["failures"]:
        record["integrity"]["failures"].append(reason)
    if record["final_status"] == "evaluated":
        record["final_status"] = "baseline_failed" if not baseline_ok else "resource_failed"
    return False


def _rerun_submission_impl(
    task_id: str,
    tasks_root: Path,
    config_path: Path,
    submission: Path,
    output_dir: Path,
    *,
    trial_id: str = "rerun",
    repair_round: int = 0,
    blender: Path | None = None,
    timeout: float | None = None,
    evaluate: bool = True,
    on_phase: Callable[[str, str, dict[str, Any]], None] | None = None,
    deadline: float | None = None,
    expected_binding: dict[str, Any] | None = None,
    _failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run an existing ``solution.py`` for every frozen seed and evaluate seed 0.

    Raw seed directories remain evidence. The first declared seed's authorized,
    self-contained comparison snapshot is copied to the run root for scoring;
    failed snapshots never fall back to mutable raw scenes or another seed.
    """

    started = time.monotonic()
    validate_repair_round(repair_round)
    task = load_benchmark_task(task_id, tasks_root)
    config: HarnessConfig = load_config(config_path)
    budget = DeadlineBudget.start(config.max_total_seconds, deadline=deadline, started=started)
    persistence = JsonPersistence(budget.deadline)

    def persist_json(path: Path, value: Any) -> None:
        """Publish Harness-owned JSON with one shared deadline session."""
        cleanup = budget.exhausted or persistence.cleanup_deadline is not None
        with persistence_scope(persistence):
            if cleanup:
                persistence.write(path, value, cleanup=True)
            else:
                write_json(path, value)

    def persist_json_atomic(path: Path, value: Any) -> None:
        cleanup = budget.exhausted or persistence.cleanup_deadline is not None
        with persistence_scope(persistence):
            if cleanup:
                persistence.write(path, value, cleanup=True)
            else:
                write_json_atomic(path, value)
    total_timeout = positive_seconds(
        config.timeout_seconds if timeout is None else timeout, "timeout"
    )
    if config.task_id != task.task_id:
        raise ValueError(
            f"Harness task_id {config.task_id} does not match {task.task_id}"
        )
    task.validate_materialized_assets()
    _spec_path, spec = _task_spec(task)
    configuration = configuration_snapshot(task, config, _spec_path, spec, expected=expected_binding)
    source = submission.expanduser().resolve()
    source_root = source if source.is_dir() else source.parent
    output_dir = output_dir.expanduser().resolve()
    output_path_receipt = ensure_directory(output_dir, deadline=budget.deadline, parents=True)
    run_id = f"{task.task_id.replace('/', '__')}__{trial_id}__{time.time_ns()}"
    run_dir = output_dir / "harness" / run_id
    run_path_receipt = ensure_directory(run_dir, deadline=budget.deadline, parents=True)
    trusted_record = output_dir / "harness_records" / f"{run_id}.json"
    record_index = run_dir / "record_index.json"
    global_index = output_dir / "harness_records" / "index" / f"{run_id}.json"
    if _failure_context is not None:
        _failure_context.update(
            run_dir=run_dir,
            trusted_record=trusted_record,
            record_index=record_index,
            global_index=global_index,
            output_dir=output_dir,
            task_id=task.task_id,
            run_id=run_id,
            deadline=budget.deadline,
            persistence=persistence,
            output_path_io=output_path_receipt["execution"],
            run_path_io=run_path_receipt["execution"],
        )
    trusted_path_receipt = ensure_directory(
        trusted_record.parent, deadline=budget.deadline, parents=True
    )
    if _failure_context is not None:
        _failure_context.update(
            trusted_path_io=trusted_path_receipt["execution"],
            persist_json_atomic=persist_json_atomic,
        )
    _spec_path = save_configuration(run_dir / "configuration", configuration, spec)
    execution_policy = {
        "configured_timeout_seconds": config.timeout_seconds,
        "timeout_override_seconds": timeout,
        "effective_timeout_seconds": total_timeout,
        "deadline_monotonic": budget.deadline,
        "seeds": list(spec.seeds),
        "trial_id": trial_id, "repair_round": repair_round,
        "baseline_policy": "provided_artifacts_or_one_independent_execution",
        "baseline_program_seed": spec.seeds[0],
        "note": "Each call is additionally capped by the remaining shared deadline",
    }
    persist_json(run_dir / "configuration/runtime.json", {"phase": "rerun", **execution_policy})
    snapshot_root = run_dir / "source_snapshot"
    submission_metadata = stage_submission(
        source,
        snapshot_root,
        reserved_outputs=spec.required_artifacts,
        entrypoint_policy=config.entrypoint_policy,
        deadline=budget.deadline,
    )
    snapshot_io_receipt = None
    if not budget.exhausted:
        snapshot_io_receipt = audit_directory(snapshot_root, deadline=budget.deadline)
    original_artifacts = _freeze_original_artifacts(
        source_root, snapshot_root, spec.required_artifacts, deadline=budget.deadline
    )
    # Freeze once, then stage this snapshot for every seed. The candidate source
    # is never reread after this point, so a seed cannot alter later inputs.
    stage_submission(
        snapshot_root,
        run_dir,
        reserved_outputs=spec.required_artifacts,
        entrypoint_policy=config.entrypoint_policy,
        deadline=budget.deadline,
    )
    source_snapshot_digest = sha256_bytes(
        json.dumps(submission_metadata, sort_keys=True, ensure_ascii=False).encode()
    )
    staging_seconds = time.monotonic() - started
    if on_phase is not None:
        on_phase("freeze", "completed", {
            "run_dir": str(run_dir),
            "source_snapshot": {
                "path": str(snapshot_root), "digest": source_snapshot_digest,
                "original_artifacts": original_artifacts,
                "workspace_io": snapshot_io_receipt["result"] if snapshot_io_receipt is not None else None,
            },
            "submission": submission_metadata,
        })
    prompt_hash = None
    source_prompt = source_root / "run_manifest.json"
    if source_prompt.is_file():
        try:
            prompt_hash = json.loads(source_prompt.read_text(encoding="utf-8")).get(
                "prompt_sha256"
            )
        except (OSError, ValueError):
            prompt_hash = None

    per_seed: dict[str, Any] = {}
    reproduction_results: dict[str, Any] = {}
    launcher_discovery: list[dict] = []
    if _failure_context is not None:
        _failure_context["launcher_discovery"] = launcher_discovery
    requested_blender = str(blender) if blender is not None else os.environ.get("BLENDER_BIN", "blender")
    reproduction_blender, initial_launcher = _resolve_blender_entrypoint(
        requested_blender, deadline=budget.deadline, phase="reconstruction",
        receipts=launcher_discovery,
    )
    canonical_execution: Execution | None = None
    budget_exhausted = budget.exhausted
    if on_phase is not None:
        on_phase("rerun", "started", {"run_dir": str(run_dir), "seeds": list(spec.seeds)})
    baseline = _prepare_baseline(
        task=task, spec=spec, config=config, source_root=source_root, snapshot_root=snapshot_root,
        run_dir=run_dir, source_digest=source_snapshot_digest, submission_metadata=submission_metadata,
        original_artifacts=original_artifacts, budget=budget, timeout=total_timeout, blender=reproduction_blender,
        resource_blender=reproduction_blender, on_phase=on_phase,
        trial_id=trial_id, repair_round=repair_round,
        persist_checkpoint=persist_json_atomic,
        persistence=persistence,
    )
    baseline["record_sha256"] = sha256(Path(baseline["record_path"]))
    original_paths = {name: Path(path) for name, path in baseline["comparison_artifacts"].items()}
    resource_records = {}
    canonical_binding = None
    canonical_log_io: dict[str, Any] | None = None
    for seed in spec.seeds:
        seed_dir = run_dir / "seed_runs" / str(seed)
        seed_path_receipt = ensure_directory(seed_dir, deadline=budget.deadline, parents=True)
        if not budget.exhausted:
            task.stage_environment(seed_dir)
        if not budget.exhausted:
            stage_submission(
                snapshot_root,
                seed_dir,
                reserved_outputs=spec.required_artifacts,
                entrypoint_policy=config.entrypoint_policy,
                deadline=budget.deadline,
            )
        seed_workspace_before = None
        if not budget.exhausted:
            seed_workspace_before = audit_directory(seed_dir, deadline=budget.deadline)
        remaining = budget.remaining
        execution_attempted = remaining > 0
        if remaining <= 0:
            budget_exhausted = True
            execution = Execution(
                "budget_exhausted", "EXECUTOR_BUDGET_EXHAUSTED", None, 0.0, "", ""
            )
        else:
            execution = _run_candidate_blender(
                seed_dir / "solution.py",
                seed_dir / "scene.blend",
                seed_dir,
                total_timeout,
                reproduction_blender,
                extra_env={
                    "THREEDBENCH_SEED": str(seed),
                    "BENCHMARK_SEED": str(seed),
                    "PYTHONHASHSEED": str(seed),
                    "THREEDBENCH_REPAIR_ROUND": str(repair_round),
                },
                deadline=budget.deadline,
            )
        observed_status = execution.status
        if budget.exhausted:
            budget_exhausted = True
            execution = replace(
                execution, status="budget_exhausted",
                error_code="EXECUTOR_BUDGET_EXHAUSTED",
            )
        aliases = _materialize_legacy_aliases(
            seed_dir, spec.required_artifacts, deadline=budget.deadline
        )
        hashes, missing = _artifact_state(seed_dir, spec.required_artifacts)
        seed_log_io = {
            "stdout": write_bounded_log(
                seed_dir / "blender.stdout.log", execution.stdout,
                deadline=budget.deadline,
            ),
            "stderr": write_bounded_log(
                seed_dir / "blender.stderr.log", execution.stderr,
                deadline=budget.deadline,
            ),
        }
        seed_workspace_after = None
        if not budget.exhausted:
            seed_workspace_after = audit_directory(seed_dir, deadline=budget.deadline)
        seed_integrity = _audit(seed_dir, spec.required_artifacts, hashes, submission_metadata)
        passed = execution.status == "success" and not missing and seed_integrity["passed"]
        per_seed[str(seed)] = {
            "passed": passed,
            "status": execution.status,
            "observed_status": observed_status,
            "execution_attempted": execution_attempted,
            "execution": _execution_record(execution, seed_log_io),
            "error_code": execution.error_code,
            "return_code": execution.return_code,
            "elapsed_seconds": execution.elapsed_seconds,
            "artifact_sha256": hashes,
            "missing_artifacts": missing,
            "aliases": aliases,
            "reproduction_status": "not_configured",
            "rng_trace": execution.rng_trace,
            "integrity": seed_integrity,
            "resource_binding": None,
            "repair_round": repair_round,
            "program_seed": seed,
            "execution_binding": bind_execution(
                task_id=task.task_id, trial_id=trial_id, repair_round=repair_round, program_seed=seed,
                source_digest=source_snapshot_digest, execution=execution, artifacts=hashes,
            ),
            "log_io": seed_log_io,
            "path_io": [seed_path_receipt["execution"]]
            + ([seed_workspace_before["execution"]] if seed_workspace_before is not None else [])
            + ([seed_workspace_after["execution"]] if seed_workspace_after is not None else []),
            "workspace_io": {
                "before": seed_workspace_before["result"] if seed_workspace_before is not None else None,
                "after": seed_workspace_after["result"] if seed_workspace_after is not None else None,
            },
        }
        resources = None
        if passed and not budget.exhausted:
            with persistence_scope(persistence):
                resources = freeze_comparison_artifacts(
                    blender=reproduction_blender,
                    artifacts={name: seed_dir / name for name in ("scene.blend", "scene.glb")},
                    output=run_dir / "resource_snapshots/seeds" / str(seed),
                    authority=generated_authority(seed_dir), task_id=task.task_id,
                    timeout=total_timeout, deadline=budget.deadline,
                )
            resource_records[str(seed)] = resources
            per_seed[str(seed)]["resource_binding"] = comparison_binding(resources)
        resource_intact = bool(resources and bound_comparison_intact(resources, per_seed[str(seed)]["resource_binding"]))
        per_seed[str(seed)]["resource_status"] = resources["status"] if resources else "not_started"
        per_seed[str(seed)]["resource_integrity_passed"] = resource_intact
        intact = _baseline_intact(baseline) if not budget.exhausted else False
        if intact and passed and resource_intact and not budget.exhausted:
            reproduction = compare_seed_artifacts(
                blender=reproduction_blender,
                spec_path=_spec_path,
                trusted_root=run_dir,
                original_artifacts=original_paths,
                seed_root=Path(resources["artifacts"]["scene.blend"]).parent,
                output_root=run_dir / "reproduction" / str(seed),
                task_id=task.task_id,
                trial_id=trial_id,
                program_seed=seed,
                repair_round=repair_round,
                timeout=total_timeout,
                deadline=budget.deadline,
                tolerance_m=spec.tolerances.get("dimension_m", 1e-5),
                material_tolerance=spec.tolerances.get(
                    "serialization", spec.tolerances.get("dimension_m", 1e-5)
                ),
            )
            if budget.exhausted or reproduction.get("budget_exhausted"):
                budget_exhausted = True
                reproduction = {
                    **reproduction, "status": "not_measurable", "budget_exhausted": True,
                    "reason": "Shared deadline exhausted during semantic reproduction",
                }
            reproduction_results[str(seed)] = reproduction
            reproduction["baseline_binding"] = _baseline_binding(baseline)
            reproduction["execution_attempted"] = True
            per_seed[str(seed)]["reproduction_status"] = reproduction["status"]
            if reproduction["status"] == "not_measurable" and any(
                artifact.get("status") == "not_measurable"
                for artifact in reproduction.get("artifacts", {}).values()
            ):
                budget_exhausted = budget_exhausted or any(
                    failure.get("code") == "EVALUATION_BUDGET_EXHAUSTED"
                    for artifact in reproduction.get("artifacts", {}).values()
                    for frame in artifact.get("frames", [])
                    for failure in [frame.get("failure", {})]
                )
        elif budget.exhausted:
            reproduction_results[str(seed)] = {
                "protocol": "l1-reproduction-v1", "status": "not_measurable",
                "budget_exhausted": True, "cost_seconds": 0.0,
                "execution_attempted": False,
                "reason": "Shared deadline exhausted before semantic reproduction",
            }
            per_seed[str(seed)]["reproduction_status"] = "not_measurable"
        else:
            # A failed execution is still one of the frozen seed slots. Do
            # not drop it and report success from the subset that was compared.
            reproduction_results[str(seed)] = {
                "protocol": "l1-reproduction-v1", "status": "not_measurable",
                "execution_attempted": False, "cost_seconds": 0.0,
                "reason": "Independent baseline unavailable or changed" if not intact else
                          "Seed execution did not produce intact required artifacts" if not passed else
                          "Seed resource snapshot unavailable or changed",
                "candidate_execution_status": execution.status,
                "baseline_status": baseline["status"],
                "baseline_binding": _baseline_binding(baseline),
                "missing_artifacts": missing,
            }
            per_seed[str(seed)]["reproduction_status"] = "not_measurable"
        per_seed[str(seed)]["budget"] = budget.record("seed")
        reproduction_results[str(seed)].setdefault("baseline_binding", _baseline_binding(baseline))
        reproduction_results[str(seed)]["resource_binding"] = per_seed[str(seed)]["resource_binding"]
        reproduction_results[str(seed)]["execution_binding"] = per_seed[str(seed)]["execution_binding"]
        reproduction_results[str(seed)]["repair_round"] = repair_round
        reproduction_results[str(seed)]["program_seed"] = seed
        if seed == spec.seeds[0]:
            canonical_execution = execution
            canonical_log_io = seed_log_io
            if resource_intact and not budget.exhausted:
                canonical_binding = {"program_seed": seed, "resource_binding": per_seed[str(seed)]["resource_binding"],
                                     "artifact_sha256": dict(resources["artifact_sha256"])}
                for name, source_path in resources["artifacts"].items():
                    copy_regular_files(
                        Path(source_path).parent,
                        run_dir,
                        (Path(source_path).name,),
                        target_files=(name,),
                        deadline=budget.deadline,
                    )
        if on_phase is not None:
            on_phase("seed", "completed" if passed else "failed", {
                "seed": seed, "run_dir": str(seed_dir), **per_seed[str(seed)],
            })

    run_workspace_after_receipt = None
    if not budget.exhausted:
        run_workspace_after_receipt = audit_directory(run_dir, deadline=budget.deadline)
    aliases = _materialize_legacy_aliases(
        run_dir, spec.required_artifacts, deadline=budget.deadline
    )
    artifact_hashes, missing_artifacts = _artifact_state(
        run_dir, spec.required_artifacts
    )
    integrity = _audit(
        run_dir, spec.required_artifacts, artifact_hashes, submission_metadata
    )
    baseline_intact = _baseline_intact(baseline) if not budget.exhausted else False
    resources_intact = True
    for seed in spec.seeds:
        key = str(seed)
        seed_intact = bool(not budget.exhausted and key in resource_records and bound_comparison_intact(
            resource_records[key], per_seed[key]["resource_binding"]))
        per_seed[key]["resource_integrity_passed"] = seed_intact
        resources_intact = resources_intact and seed_intact
        if not seed_intact and reproduction_results[key].get("status") in {"ok", "failed"}:
            reproduction_results[key].update(status="not_measurable", reason="Seed resource evidence changed or unavailable")
            per_seed[key]["reproduction_status"] = "not_measurable"
    canonical_intact = bool(canonical_binding and all(
        artifact_hashes.get(name) == digest for name, digest in canonical_binding["artifact_sha256"].items()))
    if not baseline_intact:
        integrity["passed"] = False
        integrity["failures"].append("reconstruction baseline unavailable or changed")
    if not resources_intact or not canonical_intact:
        integrity["passed"] = False
        integrity["failures"].append("seed resource snapshots or canonical derivation unavailable or changed")
    budget_exhausted = budget_exhausted or budget.exhausted
    record = {
        "schema_version": 1,
        "harness_version": config.harness_version,
        "configuration": configuration,
        "execution_policy": execution_policy,
        "launcher_discovery": launcher_discovery,
        "harness_config_sha256": config.digest,
        "evaluator_version": EVALUATOR_VERSION,
        "task_id": task.task_id,
        "trial_id": trial_id,
        "repair_round": repair_round,
        "run_id": run_id,
        "spec_sha256": spec.digest,
        "artifact_sha256": artifact_hashes,
        "execution_passed": bool(
            canonical_execution
            and canonical_execution.status == "success"
            and not missing_artifacts
        ),
        "integrity_passed": integrity["passed"],
        "integrity": integrity,
        "seed_runs": per_seed,
        "reconstruction_baseline": baseline,
        "baseline_integrity_passed": baseline_intact,
        "resource_snapshots": {"baseline": baseline["resources"], "per_seed": resource_records},
        "resource_integrity_passed": baseline_intact and resources_intact and canonical_intact,
        "provenance_status": "verified" if integrity["passed"] else "unverified",
        "not_measurable": not (baseline_intact and resources_intact and canonical_intact),
        "resource_invalidation": None,
        "canonical_derivation": canonical_binding,
        "missing_artifacts": missing_artifacts,
        "aliases": aliases,
        "submission": submission_metadata,
        "runtime_versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "blender": str(reproduction_blender),
        },
        "source_snapshot": {
            "path": str(snapshot_root),
            "digest": source_snapshot_digest,
            "original_artifacts": original_artifacts,
            "workspace_io": snapshot_io_receipt["result"] if snapshot_io_receipt is not None else None,
            "reconstruction_baseline": _baseline_binding(baseline),
            "semantic_comparison": (
                "not_configured"
                if not reproduction_results
                else "per_seed"
            ),
        },
        "reproduction_consistency": {
            "status": "not_configured"
            if not reproduction_results
            else "not_measurable"
            if not baseline_intact or set(reproduction_results) != {str(seed) for seed in spec.seeds}
            or any(item.get("status") in {"not_measurable", "not_configured"} for item in reproduction_results.values())
            else "ok"
            if all(item.get("status") == "ok" for item in reproduction_results.values())
            else "failed",
            "per_seed": reproduction_results,
            "expected_seeds": list(spec.seeds),
            "denominator": len(spec.seeds),
            "passed_count": sum(item.get("status") == "ok" for item in reproduction_results.values()),
            "measured_count": sum(item.get("status") in {"ok", "failed"} for item in reproduction_results.values()),
            "protocol": "l1-reproduction-v1",
            "reason": None if baseline_intact else "Independent baseline unavailable or changed",
            "baseline_binding": _baseline_binding(baseline),
        },
        "budget_exhausted": budget_exhausted,
        "budget": budget.record("rerun"),
        "evaluation_completed": False,
        "evaluation_budget_exhausted": False,
        "report_binding": None,
        "costs": {
            "protocol": "l1-cost-v1",
            "staging_seconds": max(0.0, float(staging_seconds)),
            "execution_seconds": baseline["execution_seconds"] + float(
                sum(
                    item["elapsed_seconds"]
                    for item in per_seed.values()
                    if isinstance(item.get("elapsed_seconds"), (int, float))
                )
            ),
            "reproduction_seconds": float(
                sum(
                    item.get("cost_seconds", 0.0)
                    for item in reproduction_results.values()
                    if isinstance(item.get("cost_seconds"), (int, float))
                )
            ),
            "evaluation_seconds": None,
            "resource_snapshot_seconds": sum(item.get("cost_seconds", 0.) for item in
                                             [baseline["resources"], *resource_records.values()] if item),
            "total_seconds": time.monotonic() - started,
            "model_calls": None,
            "total_tokens": None,
            "tool_calls": None,
            "sources": {
                "reconstruction_baseline": {
                    "wall_seconds": baseline["cost_seconds"], "execution_seconds": baseline["execution_seconds"],
                    "runs": int(baseline["execution_attempted"]), "status": baseline["status"],
                    "accounting": "Inclusive phase; execution and resource freezing also appear in candidate_blender/resource_snapshots, do not sum twice",
                },
                "resource_snapshots": {
                    "wall_seconds": sum(item.get("cost_seconds", 0.) for item in
                                        [baseline["resources"], *resource_records.values()] if item),
                    "runs": sum(bool(item.get("execution_attempted")) for item in
                                [baseline["resources"], *resource_records.values()] if item),
                    "calls": sum(bool(item.get("call_attempted")) for item in
                                 [baseline["resources"], *resource_records.values()] if item),
                    "baseline_runs": int(bool(baseline["resources"] and baseline["resources"].get("execution_attempted"))),
                    "seed_runs": sum(bool(item.get("execution_attempted")) for item in resource_records.values()),
                    "status": "budget_exhausted" if budget_exhausted else "completed"
                              if baseline_intact and resources_intact else "incomplete",
                    "accounting": "Trusted image workers only, distinct from candidate executions; baseline phase is inclusive",
                },
                "staging": {
                    "wall_seconds": max(0.0, float(staging_seconds)),
                    "status": "completed",
                },
                "candidate_blender": {
                    "wall_seconds": None
                    if not baseline["execution_attempted"] and not any(item["execution_attempted"] for item in per_seed.values())
                    else baseline["execution_seconds"] + float(
                        sum(
                            item["elapsed_seconds"]
                            for item in per_seed.values()
                            if isinstance(item.get("elapsed_seconds"), (int, float))
                        )
                    ),
                    "runs": int(baseline["execution_attempted"]) + sum(item["execution_attempted"] for item in per_seed.values()),
                    "baseline_runs": int(baseline["execution_attempted"]),
                    "seed_runs": sum(item["execution_attempted"] for item in per_seed.values()),
                    "status": "budget_exhausted" if budget_exhausted else "completed",
                },
                "reproduction": {
                    "wall_seconds": None
                    if not reproduction_results
                    else float(
                        sum(
                            item.get("cost_seconds", 0.0)
                            for item in reproduction_results.values()
                            if isinstance(item.get("cost_seconds"), (int, float))
                        )
                    ),
                    "runs": sum(item.get("execution_attempted", False) for item in reproduction_results.values()),
                    "status": "budget_exhausted" if budget_exhausted and reproduction_results
                    else "completed" if reproduction_results else "not_configured",
                },
                "evaluator": {
                    "wall_seconds": None,
                    "status": "not_started",
                },
                "model_service": {
                    "token_count": None,
                    "tool_calls": None,
                    "status": "unknown",
                },
            },
        },
        "execution": _execution_record(canonical_execution, canonical_log_io)
        if canonical_execution
        else {"status": "not_run"},
        "path_io": [
            output_path_receipt["execution"],
            run_path_receipt["execution"],
            trusted_path_receipt["execution"],
        ]
        + ([run_workspace_after_receipt["execution"]] if run_workspace_after_receipt is not None else []),
        "prompt_sha256": prompt_hash,
        "final_status": "budget_exhausted" if budget_exhausted else "baseline_failed" if not baseline_intact else
                        "seed_failed" if not all(item["passed"] for item in per_seed.values()) else
                        "resource_failed" if not resources_intact or not canonical_intact else "evaluated",
    }
    refresh_unknown_costs(record["costs"])
    record["rng_evidence"] = summarize_rng_evidence(record)
    persist_json(
        run_dir / "artifacts.json",
        {
            "required": list(spec.required_artifacts),
            "outputs": artifact_hashes,
            "seed_runs": per_seed,
            "source_snapshot": record["source_snapshot"],
        },
    )
    record["record_persistence"] = persistence.evidence()
    persist_json(run_dir / "harness_record.json", record)
    persist_json(trusted_record, record)
    local_record_sha = latest_write_receipt(run_dir / "harness_record.json", persistence)["sha256"]
    trusted_record_sha = latest_write_receipt(trusted_record, persistence)["sha256"]
    persist_json_atomic(record_index, {
        "protocol": "l1-harness-record-index-v1",
        "task_id": task.task_id,
        "run_id": run_id,
        "final_status": record["final_status"],
        "local_record": str(run_dir / "harness_record.json"),
        "local_record_sha256": local_record_sha,
        "trusted_record": str(trusted_record),
        "trusted_record_sha256": trusted_record_sha,
        "provenance_status": "verified" if record["integrity_passed"] else "unverified",
        "resource_integrity_passed": record.get("resource_integrity_passed"),
        "not_measurable": record.get("not_measurable", record.get("reproduction_consistency", {}).get("status") == "not_measurable"),
        "resource_invalidation": record.get("resource_invalidation"),
        "report": record.get("report_binding"),
        "global_index": str(global_index),
        "record_persistence": persistence.evidence(),
    })
    result: dict[str, Any] = {
        "run_dir": str(run_dir),
        "harness_record": str(trusted_record),
        "run_harness_record": str(run_dir / "harness_record.json"),
        "record_index": str(record_index),
        "global_index": None,
        "report_binding": None,
        "seed_runs": per_seed,
        "final_status": record["final_status"],
    }
    if on_phase is not None:
        on_phase("rerun", "completed" if record["final_status"] == "evaluated" else "failed", {
            "run_dir": str(run_dir), "record": str(trusted_record),
            "status": record["final_status"], "seed_runs": per_seed,
        })
    pre_evaluation_resources_ok = False
    if evaluate:
        remaining = budget.remaining
        if remaining <= 0:
            budget_exhausted = True
            record["budget_exhausted"] = True
            record["evaluation_budget_exhausted"] = True
            record["costs"]["sources"]["evaluator"]["status"] = "not_started_budget_exhausted"
            record["final_status"] = "evaluation_budget_exhausted"
            result["final_status"] = record["final_status"]
            if on_phase is not None:
                on_phase("inspection", "skipped", {"reason": "evaluation_budget_exhausted"})
                on_phase("scoring", "skipped", {"reason": "evaluation_budget_exhausted"})
        else:
            if on_phase is not None:
                on_phase("inspection", "started", {"run_dir": str(run_dir)})
            pre_evaluation_resources_ok = _refresh_resource_integrity(record, run_dir, budget)
            result["final_status"] = record["final_status"]
            blender_path, _ = _resolve_blender_entrypoint(
                requested_blender, deadline=budget.deadline, phase="evaluation",
                receipts=launcher_discovery, expected=initial_launcher,
            )
            evaluation_started = time.monotonic()
            report = evaluate_l1_submission(
                spec,
                run_dir,
                blender_path,
                assets_root=task.root,
                harness_record=record,
                timeout=min(total_timeout, remaining),
                task_id=task.task_id,
                trial_id=trial_id,
                deadline=budget.deadline,
                **({"on_phase": on_phase} if on_phase is not None else {}),
            )
            if _failure_context is not None:
                _failure_context["finalization_report"] = report
            if report.get("scoring_failed"):
                compute = report.get("compute_execution", {})
                cleanup_end = compute.get("record_persistence", {}).get("cleanup_deadline_monotonic")
                if cleanup_end is not None:
                    persistence.cleanup_deadline = min(persistence.begin_cleanup(), cleanup_end)
            record["costs"]["evaluation_seconds"] = (
                time.monotonic() - evaluation_started
            )
            record["costs"]["sources"]["evaluator"] = {
                "wall_seconds": record["costs"]["evaluation_seconds"],
                "status": "budget_exhausted"
                if report.get("budget_exhausted") or budget.exhausted
                else "failed" if report.get("scoring_failed") else "completed",
            }
            refresh_unknown_costs(record["costs"])
            record["evaluation_budget_exhausted"] = bool(
                report.get("budget_exhausted") or budget.exhausted
            )
            record["evaluation_completed"] = not record["evaluation_budget_exhausted"] and not report.get("scoring_failed", False)
            if "finalization" in report:
                # Preserve the actual accepted ACK outside the report bytes;
                # a raw pending report file is never sufficient for replay.
                record["evaluation_finalization"] = report["finalization"]
            if record["evaluation_budget_exhausted"]:
                record["budget_exhausted"] = True
                record["final_status"] = "evaluation_budget_exhausted"
                result["final_status"] = record["final_status"]
            elif report.get("scoring_failed"):
                record["final_status"] = "scoring_failed"
                result["final_status"] = record["final_status"]
            result["report"] = report
            result["report_path"] = report["report_path"]
            record["report_binding"] = _report_binding(report)
            result["report_binding"] = record["report_binding"]
    elif on_phase is not None:
        on_phase("inspection", "skipped", {"reason": "not_requested"})
        on_phase("scoring", "skipped", {"reason": "not_requested"})
    if (not budget.exhausted and persistence.cleanup_deadline is None
            and not _refresh_resource_integrity(record, run_dir, budget)):
        result["final_status"] = record["final_status"]
        if "report" in result and (pre_evaluation_resources_ok or result["report"].get("case_pass")
                                   or result["report"].get("G")):
            observed = result["report"]
            record["evaluation_completed"] = False
            if _failure_context is not None:
                _failure_context["resource_invalidation"] = record.get("resource_invalidation")
                _failure_context["superseded_report"] = {
                    "path": observed["report_path"], "finalization": observed.get("finalization"),
                    "role": "historical_only_not_current_result",
                }
            result["report"] = recommit_resource_failure(
                spec, observed, record.get("resource_invalidation"), persistence=persistence,
            )
            result["report_path"] = result["report"]["report_path"]
            record["evaluation_finalization"] = result["report"]["finalization"]
            record["report_binding"] = _report_binding(result["report"])
            result["report_binding"] = record["report_binding"]
    record["costs"]["total_seconds"] = time.monotonic() - started
    record["rng_evidence"] = summarize_rng_evidence(record)
    record["budget"] = budget.record("rerun")
    if budget.exhausted:
        record["budget_exhausted"] = True
        if record["final_status"] == "evaluated":
            record["final_status"] = "budget_exhausted"
            result["final_status"] = record["final_status"]
    record["record_persistence"] = persistence.evidence()
    persist_json(run_dir / "harness_record.json", record)
    persist_json(trusted_record, record)
    # Scoring changes the record after its initial checkpoint. Both indexes
    # must describe this final revision, not the pre-evaluation hashes.
    local_record_sha = latest_write_receipt(run_dir / "harness_record.json", persistence)["sha256"]
    trusted_record_sha = latest_write_receipt(trusted_record, persistence)["sha256"]
    persist_json_atomic(record_index, {
        "protocol": "l1-harness-record-index-v1",
        "task_id": task.task_id,
        "run_id": run_id,
        "final_status": record["final_status"],
        "local_record": str(run_dir / "harness_record.json"),
        "local_record_sha256": local_record_sha,
        "trusted_record": str(trusted_record),
        "trusted_record_sha256": trusted_record_sha,
        "provenance_status": record.get("provenance_status", "verified" if record["integrity_passed"] else "unverified"),
        "resource_integrity_passed": record.get("resource_integrity_passed"),
        "not_measurable": record.get("not_measurable", record.get("reproduction_consistency", {}).get("status") == "not_measurable"),
        "resource_invalidation": record.get("resource_invalidation"),
        "report": record.get("report_binding"),
        "global_index": str(global_index),
        "record_persistence": persistence.evidence(),
    })
    global_index_receipt = publish_global_index(
        output_dir,
        run_id,
        {
            "task_id": task.task_id,
            "final_status": record["final_status"],
            "local_record": str(run_dir / "harness_record.json"),
            "local_record_sha256": local_record_sha,
            "trusted_record": str(trusted_record),
            "trusted_record_sha256": trusted_record_sha,
            "record_index": str(record_index),
            "record_index_sha256": latest_write_receipt(record_index, persistence)["sha256"],
            "provenance_status": record.get("provenance_status", "verified" if record["integrity_passed"] else "unverified"),
            "resource_integrity_passed": record.get("resource_integrity_passed"),
            "not_measurable": record.get("not_measurable", record.get("reproduction_consistency", {}).get("status") == "not_measurable"),
            "resource_invalidation": record.get("resource_invalidation"),
            "report": record.get("report_binding"),
        },
        deadline=budget.deadline,
        persistence=persistence,
        cleanup=budget.exhausted or persistence.cleanup_deadline is not None,
    )
    result["global_index"] = global_index_receipt
    return result


def _publish_rerun_failure(context: dict[str, Any], error: BaseException) -> None:
    """Append failure evidence without replacing any prior rerun checkpoints."""
    try:
        result = publish_failure_records(context, error, stage="rerun")
    except BaseException as publication_error:  # noqa: BLE001 -- preserve original failure
        # Reporting failure must not replace a worker error or cancellation.
        error.l1_failure_publication_error = type(publication_error).__name__
        return
    if not result:
        return
    try:
        error.l1_failure_publication = result
        error.l1_rerun_failure_record = result["harness_record"]
    except (AttributeError, TypeError):
        pass


def rerun_submission(
    task_id: str,
    tasks_root: Path,
    config_path: Path,
    submission: Path,
    output_dir: Path,
    *,
    trial_id: str = "rerun",
    repair_round: int = 0,
    blender: Path | None = None,
    timeout: float | None = None,
    evaluate: bool = True,
    on_phase: Callable[[str, str, dict[str, Any]], None] | None = None,
    deadline: float | None = None,
    expected_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    token = _RERUN_FAILURE_CONTEXT.set(context)
    try:
        return _rerun_submission_impl(
            task_id, tasks_root, config_path, submission, output_dir,
            trial_id=trial_id, repair_round=repair_round, blender=blender,
            timeout=timeout, evaluate=evaluate, on_phase=on_phase,
            deadline=deadline, expected_binding=expected_binding,
            _failure_context=context,
        )
    except BaseException as error:
        _publish_rerun_failure(context, error)
        raise
    finally:
        _RERUN_FAILURE_CONTEXT.reset(token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rerun an existing L1 solution for frozen seeds and evaluate it"
    )
    parser.add_argument("--task", required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--harness-config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs"))
    parser.add_argument("--trial-id", default="rerun")
    parser.add_argument("--repair-round", type=int, default=0)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--no-evaluate", action="store_true")
    args = parser.parse_args()
    try:
        tasks_root = args.tasks_root.expanduser().resolve()
        config_path = args.harness_config or _task_config_default(args.task, tasks_root)
        result = rerun_submission(
            args.task,
            tasks_root,
            config_path.expanduser().resolve(),
            args.submission,
            args.output_dir,
            trial_id=args.trial_id,
            repair_round=args.repair_round,
            blender=args.blender,
            timeout=args.timeout,
            evaluate=not args.no_evaluate,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"[l1-rerun] error: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final_status"] == "evaluated" and result.get("report", {}).get("case_pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
