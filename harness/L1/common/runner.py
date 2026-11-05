"""First-stage L1 harness runner for Codex generation attempts."""

from __future__ import annotations

import argparse
import inspect
import json
import platform
import tempfile
import time
from contextvars import ContextVar
from dataclasses import replace
from src.generator.harnesses import model_effort, model_contract
from pathlib import Path
from typing import Any

from src.evaluator.l1_budget import DeadlineBudget
from src.evaluator.l1_log_io import write_bounded_file, write_bounded_log
from src.evaluator.l1_parent_io import (
    audit_directory,
    copy_regular_files,
    ensure_directory,
)
from src.evaluator.l1_persistence import JsonPersistence
from src.evaluator.spec import EVALUATOR_VERSION, EvalSpec
from src.generator.client import (
    BENCHMARK_TASK_PROMPT,
    GeneratorConfig,
)
from src.generator.task_adapter import load_benchmark_task

from .attempt_log import (
    persistence_scope,
    sha256,
    sha256_bytes,
    write_json,
    write_json_atomic,
)
from .blender_executor import Execution, run_blender
from .bundle import BUNDLE_PROTOCOL, delivery_prompt, materialize_bundle
from .codex_invoker import DEFAULT_WORKSPACE_LIMITS, Invocation, run_once
from .config import HarnessConfig, load_config
from .configuration import configuration_snapshot, save_configuration, task_spec
from .costs import refresh_unknown_costs
from .execution_provenance import validate_repair_round
from .failure_record import publish_failure_records
from .global_index import latest_write_receipt, publish_global_index
from .repair_context import (
    context_intact,
    context_prompt,
    prepare_context,
    stage_context,
)
from .submission import MANIFEST_NAME, stage_submission

_GENERATION_FAILURE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "l1_generation_failure_context", default=None
)


def _task_config_default(task_id: str, tasks_root: Path) -> Path:
    return tasks_root.joinpath(*task_id.split("/")) / "harness" / "harness.toml"


def _task_spec(task: Any) -> tuple[Path, EvalSpec]:
    return task_spec(task)


def _prompt(task: Any) -> str:
    files = (
        "\n".join(f"- {p.as_posix()}" for p in task.environment_files)
        or "- (none; text-only task)"
    )
    return f"{delivery_prompt(task.task_id).strip()}\n\n{BENCHMARK_TASK_PROMPT.format(environment_files=files, instruction=task.instruction).strip()}\n"


def _retryable(invocation: Invocation, config: HarnessConfig) -> bool:
    if invocation.status == "timeout":
        return config.retry.retry_timeout
    if invocation.status == "process_error":
        return config.retry.retry_transport_error
    if invocation.status == "empty_output":
        return config.retry.retry_empty_output
    if invocation.status == "protocol_error":
        return config.retry.retry_protocol_error
    return False


def _attempt_record(
    index: int, invocation: Invocation, output_path: Path
) -> dict[str, Any]:
    record = {
        "attempt": index,
        "status": invocation.status,
        "error_code": invocation.error_code,
        "return_code": invocation.return_code,
        "elapsed_seconds": invocation.elapsed_seconds,
        "stdout_sha256": sha256_bytes(invocation.stdout.encode()),
        "stderr_sha256": sha256_bytes(invocation.stderr.encode()),
        "output_sha256": sha256(output_path) if not output_path.is_symlink() and output_path.is_file() else None,
        "retryable_status": invocation.status
        in {
            "timeout",
            "process_error",
            "empty_output",
            "protocol_error",
        },
    }
    if invocation.output_io is not None:
        record["output_io"] = invocation.output_io
    if invocation.resource_limits is not None:
        record["resource_limits"] = invocation.resource_limits
    if invocation.workspace_guard is not None:
        record["workspace_guard"] = invocation.workspace_guard
    if invocation.launcher_io is not None:
        record["launcher_io"] = invocation.launcher_io
    return record


def _invoke_codex(
    config: GeneratorConfig,
    prompt: str,
    workspace: Path,
    output_path: Path,
    timeout: float,
    image_paths: list[Path],
    *,
    deadline: float,
) -> Invocation:
    """Call the production invoker with quota policy, preserving test seams.

    Older local adapters may expose the pre-quota call signature. Signature
    inspection keeps those explicit substitutes usable without catching a
    real ``TypeError`` raised inside the production invoker.
    """
    kwargs: dict[str, Any] = {"deadline": deadline, "delivery_format": "bundle"}
    try:
        parameters = inspect.signature(run_once).parameters.values()
        accepts_limits = any(
            parameter.name == "workspace_limits"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
    except (TypeError, ValueError):
        accepts_limits = True
    if accepts_limits:
        kwargs["workspace_limits"] = DEFAULT_WORKSPACE_LIMITS
    return run_once(
        config, prompt, workspace, output_path, timeout, image_paths, **kwargs
    )


def _run_candidate_blender(
    script: Path,
    output: Path,
    workspace: Path,
    timeout: float,
    blender: Path | None,
    *,
    deadline: float,
) -> Execution:
    """Run Blender with the shared quota while preserving local test seams."""
    kwargs: dict[str, Any] = {"deadline": deadline}
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


def _run_impl(
    task_id: str,
    tasks_root: Path,
    config_path: Path,
    output_dir: Path,
    env_file: Path | None = None,
    trial_id: str = "0",
    blender: Path | None = None,
    *,
    execute: bool = True,
    deadline: float | None = None,
    expected_binding: dict[str, Any] | None = None,
    repair_round: int = 0,
    previous_submission: Path | None = None,
    public_feedback: dict[str, Any] | None = None,
    _failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    validate_repair_round(repair_round)
    if previous_submission is not None and public_feedback is None:
        raise ValueError('Previous submission requires allowlisted public feedback')
    if repair_round and public_feedback is None:
        raise ValueError('Repair rounds require allowlisted public feedback')
    task = load_benchmark_task(task_id, tasks_root)
    config = load_config(config_path)
    budget = DeadlineBudget.start(config.max_total_seconds, deadline=deadline, started=started)
    persistence = JsonPersistence(budget.deadline)

    def persist_json(path: Path, value: Any) -> None:
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

    if config.task_id != task.task_id:
        raise ValueError(
            f"Harness task_id {config.task_id} does not match {task.task_id}"
        )
    task.validate_materialized_assets()
    spec_path, spec = _task_spec(task)
    configuration = configuration_snapshot(task, config, spec_path, spec, expected=expected_binding)
    output_dir = output_dir.expanduser().resolve()
    output_path_receipt = ensure_directory(output_dir, deadline=budget.deadline, parents=True)
    run_id = f"{task.task_id.replace('/', '__')}__trial-{trial_id}__{time.time_ns()}"
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
        )
    trusted_path_receipt = ensure_directory(
        trusted_record.parent, deadline=budget.deadline, parents=True
    )
    if _failure_context is not None:
        _failure_context.update(
            trusted_path_io=trusted_path_receipt["execution"],
            output_path_io=output_path_receipt["execution"],
            run_path_io=run_path_receipt["execution"],
        )
    with persistence_scope(persistence):
        save_configuration(run_dir / "configuration", configuration, spec)
    prompt = _prompt(task)
    refinement_context = None
    if public_feedback is not None:
        refinement_context = prepare_context(
            run_dir, spec, repair_round=repair_round, previous=previous_submission,
            feedback=public_feedback, entrypoint_policy=config.entrypoint_policy,
            deadline=budget.deadline,
        )
        prompt += context_prompt(refinement_context)
    # Resolve the effective generator configuration before writing the
    # manifest. The TOML describes policy; the env file supplies the actual
    # model/runtime values used by this invocation.
    generator_config = GeneratorConfig.from_env(env_file)
    generator_config = replace(
        generator_config,
        max_attempts=1,
        reasoning_effort=model_effort(generator_config.model) if model_contract(generator_config.model) else config.reasoning_effort or generator_config.reasoning_effort,
    )
    if config.runtime != generator_config.runtime:
        raise ValueError(
            f"Harness runtime {config.runtime!r} does not match generator runtime {generator_config.runtime!r}"
        )
    if config.model_env != "OPENAI_MODEL":
        raise ValueError(
            "Harness model_env must be OPENAI_MODEL; custom model environment names are not supported by GeneratorConfig"
        )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": task.task_id,
        "trial_id": trial_id,
        "repair_round": repair_round,
        "refinement_context": refinement_context,
        "harness_version": config.harness_version,
        "harness_config_sha256": config.digest,
        "configuration": configuration,
        "evaluator_version": EVALUATOR_VERSION,
        "eval_spec": str(spec_path),
        "spec_sha256": spec.digest,
        "required_artifacts": list(spec.required_artifacts),
        "delivery_protocol": BUNDLE_PROTOCOL,
        "seeds": list(spec.seeds),
        "model": generator_config.model,
        "codex_binary": generator_config.codex_binary,
        "runtime": config.runtime,
        "runtime_versions": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "blender": str(blender) if blender is not None else None,
        },
        "run_instructions": {
            "entrypoint": "solution.py",
            "working_directory": "run_dir",
            "execution": "Blender factory-startup executor owns scene.blend and scene.glb outputs",
        },
        "network": config.network,
        "network_policy": {
            "declared": config.network,
            "enforced": False,
            "status": "declared_only",
            "note": "Current local executor does not provide a kernel-level network sandbox.",
        },
        "reasoning_effort": generator_config.reasoning_effort,
        "timeout_seconds": config.timeout_seconds,
        "max_attempts": config.max_attempts,
        "max_total_seconds": config.max_total_seconds,
        "budget": budget.record("generation"),
        "retry_policy": {
            "max_retries": config.retry.max_retries,
            "retry_timeout": config.retry.retry_timeout,
            "retry_transport_error": config.retry.retry_transport_error,
            "retry_empty_output": config.retry.retry_empty_output,
            "retry_protocol_error": config.retry.retry_protocol_error,
            "backoff_seconds": list(config.retry.backoff_seconds),
        },
        "environment_files": [p.as_posix() for p in task.environment_files],
        "prompt_sha256": sha256_bytes(prompt.encode())
        if config.save_prompt_hash
        else None,
        "started_at": time.time(),
    }
    persist_json_atomic(run_dir / "run_manifest.json", manifest)
    generator_policy = {
        name: manifest[name] for name in (
            "model", "codex_binary", "runtime", "reasoning_effort", "timeout_seconds",
            "max_attempts", "max_total_seconds", "retry_policy", "network_policy",
        )
    }
    persist_json(run_dir / "configuration/runtime.json", {"phase": "generation", **generator_policy})
    attempts: list[dict[str, Any]] = []
    final_invocation: Invocation | None = None
    budget_exhausted = False
    input_hashes: dict[str, str] = {}
    submission_metadata: dict[str, Any] | None = None
    invocation_error: BaseException | None = None
    invocation_failure: dict[str, str] | None = None
    # ``generator.max_attempts`` is deliberately fixed to one for each CLI
    # invocation. Outer retries belong exclusively to the harness policy.
    max_calls = config.retry.max_retries + 1
    with tempfile.TemporaryDirectory(prefix="l1-input-") as staged_name:
        staging_root = Path(staged_name)
        for index in range(1, max_calls + 1):
            if budget.exhausted:
                budget_exhausted = True
                break
            attempt_dir = run_dir / f"attempt-{index:04d}"
            attempt_path_receipt = ensure_directory(
                attempt_dir, deadline=budget.deadline, parents=True
            )
            output_path = attempt_dir / "solution.py"
            # An unsuccessful attempt cannot leave files for the next model call.
            workspace = staging_root / f'attempt-{index:04d}'
            task.stage_environment(workspace)
            stage_context(refinement_context, workspace, deadline=budget.deadline)
            workspace_path_receipt = audit_directory(workspace, deadline=budget.deadline)
            observed_inputs = {p.as_posix(): sha256(workspace / p) for p in task.environment_files}
            if index > 1 and observed_inputs != input_hashes:
                raise ValueError('Task input bytes changed between generation attempts')
            input_hashes = observed_inputs
            if budget.exhausted:
                budget_exhausted = True
                break
            invocation_started = time.monotonic()
            persist_json_atomic(attempt_dir / "result.json", {
                "attempt": index, "repair_round": repair_round, "status": "running",
                "input_sha256": dict(input_hashes), "budget": budget.record("generation_attempt"),
                "path_io": [attempt_path_receipt["execution"], workspace_path_receipt["execution"]],
            })
            try:
                invocation = _invoke_codex(
                    generator_config,
                    prompt,
                    workspace,
                    output_path,
                    config.timeout_seconds,
                    [workspace / p for p in task.image_files],
                    deadline=budget.deadline,
                )
            except (Exception, KeyboardInterrupt, SystemExit) as error:  # noqa: BLE001 - persisted, then reraised
                # The invoker's finally has already reaped its process group.
                # Persist a failed attempt and terminal generation record before
                # reraising to the service/agent; never retry cancellation.
                invocation_error = error
                invocation_failure = {"phase": "invocation", "exception_type": type(error).__name__}
                status = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "invoker_error"
                invocation = Invocation(status, "GENERATOR_INTERRUPTED" if status == "interrupted" else "GENERATOR_INVOKER_ERROR",
                                        None, time.monotonic() - invocation_started, "", "", None,
                                        launcher_io=getattr(error, "launcher_io", None))
            observed_status = invocation.status
            if invocation_error is None and not context_intact(refinement_context, workspace):
                invocation = replace(invocation, status='protocol_error',
                                     error_code='GENERATOR_REPAIR_CONTEXT_CHANGED', output=None, bundle=None)
            if budget.exhausted:
                budget_exhausted = True
                invocation = replace(
                    invocation, status="budget_exhausted",
                    error_code="GENERATOR_BUDGET_EXHAUSTED",
                )
            log_io = {}
            if config.save_stdout:
                log_io["stdout"] = write_bounded_log(
                    attempt_dir / "stdout.log", invocation.stdout,
                    deadline=budget.deadline,
                )
            if config.save_stderr:
                log_io["stderr"] = write_bounded_log(
                    attempt_dir / "stderr.log", invocation.stderr,
                    deadline=budget.deadline,
                )
            record = _attempt_record(index, invocation, output_path)
            record["log_io"] = log_io
            record["path_io"] = [attempt_path_receipt["execution"], workspace_path_receipt["execution"]]
            record['repair_round'] = repair_round
            record['input_sha256'] = dict(input_hashes)
            record['refinement_context_sha256'] = refinement_context['sha256'] if refinement_context else None
            if invocation_error is not None:
                record['failure'] = invocation_failure
                record['output_capture_status'] = 'unavailable_due_to_exception'
                record['stdout_sha256'] = record['stderr_sha256'] = None
            record["observed_status"] = observed_status
            record["budget"] = budget.record("generation_attempt")
            if not budget.exhausted:
                workspace_after_receipt = audit_directory(workspace, deadline=budget.deadline)
                record["path_io"].append(workspace_after_receipt["execution"])
                record["workspace_io"] = {
                    "before": workspace_path_receipt["result"],
                    "after": workspace_after_receipt["result"],
                }
            persist_json_atomic(attempt_dir / "result.json", record)
            attempts.append(record)
            final_invocation = invocation
            if invocation.status == "success":
                # ``run_once`` validates and normalizes Markdown-fenced model
                # output. Preserve the raw last-message response for audit,
                # but execute and publish only the normalized Python source.
                normalized = invocation.output
                if not isinstance(normalized, str) or not normalized.strip():
                    invocation = replace(
                        invocation,
                        status="protocol_error",
                        error_code="GENERATOR_PROTOCOL_ERROR",
                        output=None,
                    )
                    final_invocation = invocation
                    record = {**record, **_attempt_record(index, invocation, output_path)}
                    persist_json(attempt_dir / "result.json", record)
                    attempts[-1] = record
                else:
                    normalized_path = attempt_dir / "solution.normalized.py"
                    normalized_receipt = write_bounded_file(
                        normalized_path,
                        normalized,
                        deadline=budget.deadline,
                        replace=False,
                    )
                    response_name = "model_response.json" if invocation.bundle else "model_response.py"
                    response_receipt = copy_regular_files(
                        output_path.parent,
                        attempt_dir,
                        (output_path.name,),
                        deadline=budget.deadline,
                        target_files=(response_name,),
                    )
                    attempts[-1].setdefault("path_io", []).extend(
                        [normalized_receipt, response_receipt["execution"]]
                    )
                    try:
                        public_manifest = workspace / MANIFEST_NAME
                        if invocation.bundle is not None:
                            if public_manifest.exists() or public_manifest.is_symlink():
                                raise ValueError("Ambiguous bundle and workspace manifest delivery")
                            decoded = attempt_dir / "decoded_bundle"
                            materialize_bundle(
                                invocation.bundle, decoded, reserved_outputs=spec.required_artifacts,
                                entrypoint_policy=config.entrypoint_policy,
                            )
                            stage_submission(
                                decoded, attempt_dir / "submission", reserved_outputs=spec.required_artifacts,
                                entrypoint_policy=config.entrypoint_policy,
                                deadline=budget.deadline,
                            )
                            submission_metadata = stage_submission(
                                attempt_dir / "submission", run_dir, reserved_outputs=spec.required_artifacts,
                                entrypoint_policy=config.entrypoint_policy,
                                deadline=budget.deadline,
                            )
                            attempts[-1]["completion_source"] = BUNDLE_PROTOCOL
                        elif public_manifest.exists() or public_manifest.is_symlink():
                            # Validate/freeze a declared multi-file delivery
                            # before the model workspace is removed. Do not
                            # collect undeclared files or model-visible input/.
                            stage_submission(
                                workspace, attempt_dir / "submission",
                                reserved_outputs=spec.required_artifacts,
                                entrypoint_policy=config.entrypoint_policy,
                                deadline=budget.deadline,
                            )
                            submission_metadata = stage_submission(
                                attempt_dir / "submission", run_dir,
                                reserved_outputs=spec.required_artifacts,
                                entrypoint_policy=config.entrypoint_policy,
                                deadline=budget.deadline,
                            )
                            attempts[-1]["completion_source"] = "public_submission_manifest"
                        else:
                            copy_receipt = copy_regular_files(
                                normalized_path.parent,
                                run_dir,
                                (normalized_path.name,),
                                deadline=budget.deadline,
                                target_files=("solution.py",),
                            )
                            attempts[-1].setdefault("path_io", []).append(copy_receipt["execution"])
                            attempts[-1]["completion_source"] = "normalized_last_message"
                        attempts[-1]["normalized_output_sha256"] = sha256(normalized_path)
                        persist_json(attempt_dir / "result.json", attempts[-1])
                        break
                    except (OSError, ValueError, TypeError):
                        # An invalid declaration is a protocol failure, not a
                        # valid single-file submission with silently lost deps.
                        invocation = replace(
                            invocation, status="protocol_error",
                            error_code="GENERATOR_SUBMISSION_INVALID", output=None,
                        )
                        final_invocation = invocation
                        record = {**record, **_attempt_record(index, invocation, output_path)}
                        persist_json(attempt_dir / "result.json", record)
                        attempts[-1] = record
            if not _retryable(invocation, config) or index >= max_calls:
                break
            remaining = budget.remaining
            if remaining <= 0:
                budget_exhausted = True
                break
            backoff = config.retry.backoff_seconds[
                min(index - 1, len(config.retry.backoff_seconds) - 1)
            ]
            try:
                time.sleep(min(backoff, remaining))
            except (Exception, KeyboardInterrupt, SystemExit) as error:  # noqa: BLE001 - persisted, then reraised
                invocation_error = error
                invocation_failure = {"phase": "backoff", "exception_type": type(error).__name__}
                break
    budget_exhausted = budget_exhausted or budget.exhausted
    if invocation_error is not None:
        final_status = "interrupted" if isinstance(invocation_error, (KeyboardInterrupt, SystemExit)) else "invoker_error"
    elif budget_exhausted:
        final_status = "budget_exhausted"
    else:
        final_status = (
            final_invocation.status if final_invocation else "budget_exhausted"
        )
    generation_finished_at = time.monotonic()
    # Keep model-visible inputs alongside the generated script so execution is
    # reproducible after the temporary Codex staging directory is removed.
    if invocation_error is None and not budget.exhausted:
        task.stage_environment(run_dir)
    run_workspace_receipt = None
    if not budget.exhausted:
        run_workspace_receipt = audit_directory(run_dir, deadline=budget.deadline)
    execution: Execution | None = None
    execution_log_io: dict[str, Any] | None = None
    if execute and final_status == "success" and (run_dir / "solution.py").is_file():
        remaining = budget.remaining
        if remaining > 0:
            execution = _run_candidate_blender(
                run_dir / "solution.py",
                run_dir / "scene.blend",
                run_dir,
                config.timeout_seconds,
                blender,
                deadline=budget.deadline,
            )
            execution_log_io = {
                "stdout": write_bounded_log(
                    run_dir / "blender.stdout.log", execution.stdout,
                    deadline=budget.deadline,
                ),
                "stderr": write_bounded_log(
                    run_dir / "blender.stderr.log", execution.stderr,
                    deadline=budget.deadline,
                ),
            }
            final_status = (
                "executed"
                if execution.status == "success"
                else (f"executor_{execution.status}")
            )
        else:
            final_status = "executor_budget_exhausted"
    elif not execute and final_status == "success":
        final_status = "generated"
    run_workspace_after_receipt = None
    if not budget.exhausted:
        run_workspace_after_receipt = audit_directory(run_dir, deadline=budget.deadline)
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_hashes: dict[str, str] = {}
    missing_artifacts: list[str] = []
    for name in spec.required_artifacts:
        path = run_dir / name
        if path.is_file() and path.stat().st_size > 0:
            digest = sha256(path)
            artifact_hashes[name] = digest
            artifacts[name] = {"sha256": digest, "bytes": path.stat().st_size}
        else:
            missing_artifacts.append(name)
            artifacts[name] = {"sha256": None, "bytes": 0, "missing": True}
    persist_json(
        run_dir / "artifacts.json",
        {
            "input_sha256": input_hashes,
            "outputs": artifacts,
            "required": list(spec.required_artifacts),
        },
    )
    seed_runs = {
        str(seed): {
            "passed": False,
            "status": "not_run",
            "reason": "Seed rerun executor is a later L1 harness component",
        }
        for seed in spec.seeds
    }
    budget_exhausted = budget_exhausted or budget.exhausted
    if budget_exhausted and invocation_error is None:
        final_status = "budget_exhausted"
    record = {
        "schema_version": 1,
        "harness_version": config.harness_version,
        "configuration": configuration,
        "harness_config_sha256": config.digest,
        "generator_policy": generator_policy,
        "evaluator_version": EVALUATOR_VERSION,
        "task_id": task.task_id,
        "trial_id": trial_id,
        "repair_round": repair_round,
        "refinement_context": refinement_context,
        "run_id": run_id,
        "spec_sha256": spec.digest,
        "artifact_sha256": artifact_hashes,
        "generation_passed": final_status in {"generated", "executed"}
        and (run_dir / "solution.py").is_file(),
        "submission": submission_metadata,
        "execution_passed": final_status == "executed" and not missing_artifacts,
        "integrity_passed": False,
        "integrity": {
            "status": "pending",
            "reason": "A separate evaluator-owned audit must approve provenance and immutability",
        },
        "seed_runs": seed_runs,
        "missing_artifacts": missing_artifacts,
        "execution": (
            {
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
                "log_io": execution_log_io,
            }
            if execution is not None
            else {"status": "not_started"}
        ),
        "attempt_count": len(attempts),
        "final_status": final_status,
        "attempts": attempts,
        "budget_exhausted": budget_exhausted,
        "budget": budget.record("generation"),
        "path_io": [
            output_path_receipt["execution"],
            run_path_receipt["execution"],
            trusted_path_receipt["execution"],
        ]
        + ([run_workspace_receipt["execution"]] if run_workspace_receipt is not None else [])
        + ([run_workspace_after_receipt["execution"]] if run_workspace_after_receipt is not None else []),
        "costs": {
            "protocol": "l1-cost-v1",
            "generator_attempts": len(attempts),
            "generator_seconds": generation_finished_at - started,
            "retry_count": max(0, len(attempts) - 1),
            "token_count": None,
            "tool_calls": None,
            "sources": {
                "codex_generation": {
                    "attempts": len(attempts),
                    "wall_seconds": generation_finished_at - started,
                    "token_count": None,
                    "tool_calls": None,
                    "status": "unknown",
                },
                "candidate_blender": {
                    "wall_seconds": execution.elapsed_seconds
                    if execution is not None
                    else None,
                    "status": execution.status if execution is not None else "not_started",
                },
                "evaluator": {
                    "wall_seconds": None,
                    "token_count": None,
                    "tool_calls": None,
                    "status": "not_started",
                },
            },
        },
    }
    refresh_unknown_costs(record["costs"])
    if invocation_failure is not None:
        record['failure'] = invocation_failure
        manifest['failure'] = invocation_failure
    record["record_persistence"] = persistence.evidence()
    # The trusted record must be self-consistent with its own ACK.  Publish
    # the content first, then bind both exact hashes in the index and global
    # shard; downstream readers never infer success from a path alone.
    persist_json_atomic(run_dir / "harness_record.json", record)
    persist_json_atomic(trusted_record, record)
    local_record_sha = latest_write_receipt(run_dir / "harness_record.json", persistence)["sha256"]
    trusted_record_sha = latest_write_receipt(trusted_record, persistence)["sha256"]
    persist_json_atomic(record_index, {
        "protocol": "l1-harness-record-index-v1",
        "task_id": task.task_id,
        "run_id": run_id,
        "final_status": final_status,
        "local_record": str(run_dir / "harness_record.json"),
        "local_record_sha256": local_record_sha,
        "trusted_record": str(trusted_record),
        "trusted_record_sha256": trusted_record_sha,
        "provenance_status": "verified" if record["integrity_passed"] else "unverified",
        "resource_integrity_passed": None,
        "not_measurable": False,
        "global_index": str(global_index),
        "record_persistence": persistence.evidence(),
    })
    global_index_receipt = publish_global_index(
        output_dir,
        run_id,
        {
            "task_id": task.task_id,
            "final_status": final_status,
            "local_record": str(run_dir / "harness_record.json"),
            "local_record_sha256": local_record_sha,
            "trusted_record": str(trusted_record),
            "trusted_record_sha256": trusted_record_sha,
            "record_index": str(record_index),
            "record_index_sha256": latest_write_receipt(record_index, persistence)["sha256"],
            "provenance_status": "verified" if record["integrity_passed"] else "unverified",
            "not_measurable": False,
        },
        deadline=budget.deadline,
        persistence=persistence,
        cleanup=budget.exhausted or persistence.cleanup_deadline is not None,
    )
    manifest.update(
        {
            "finished_at": time.time(),
            "attempt_count": len(attempts),
            "final_status": final_status,
            "execution": record["execution"],
            "generation_passed": record["generation_passed"],
            "artifact_sha256": artifact_hashes,
            "missing_artifacts": missing_artifacts,
            "trusted_harness_record": str(trusted_record),
            "record_index": str(record_index),
            "global_index": global_index_receipt,
            "budget": record["budget"],
        }
    )
    manifest["record_persistence"] = persistence.evidence()
    persist_json_atomic(run_dir / "run_manifest.json", manifest)
    result = {
        "run_dir": str(run_dir),
        "harness_record": str(trusted_record),
        "run_harness_record": str(run_dir / "harness_record.json"),
        "record_index": str(record_index),
        "global_index": global_index_receipt,
        "final_status": final_status,
        "attempt_count": len(attempts),
    }
    if invocation_error is not None:
        # A trusted caller can bind this failure record without scanning for
        # arbitrary files. It must still validate configuration/task/round.
        invocation_error.l1_generation_result = result
        raise invocation_error
    return result


def _publish_generation_failure(context: dict[str, Any], error: BaseException) -> None:
    """Append failure evidence without replacing a published generation."""
    result = publish_failure_records(context, error, stage="generation")
    if not result:
        return
    try:
        error.l1_failure_publication = result
        # A completed invocation failure already carries its full trusted
        # configuration binding; keep it for the refinement caller.
        if not isinstance(getattr(error, "l1_generation_result", None), dict):
            error.l1_generation_result = result
    except (AttributeError, TypeError):
        pass


def run(
    task_id: str,
    tasks_root: Path,
    config_path: Path,
    output_dir: Path,
    env_file: Path | None = None,
    trial_id: str = "0",
    blender: Path | None = None,
    *,
    execute: bool = True,
    deadline: float | None = None,
    expected_binding: dict[str, Any] | None = None,
    repair_round: int = 0,
    previous_submission: Path | None = None,
    public_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    token = _GENERATION_FAILURE_CONTEXT.set(context)
    try:
        return _run_impl(
            task_id, tasks_root, config_path, output_dir, env_file,
            trial_id, blender, execute=execute, deadline=deadline,
            expected_binding=expected_binding, repair_round=repair_round,
            previous_submission=previous_submission, public_feedback=public_feedback,
            _failure_context=context,
        )
    except BaseException as error:
        _publish_generation_failure(context, error)
        raise
    finally:
        _GENERATION_FAILURE_CONTEXT.reset(token)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a first-stage L1 generation harness"
    )
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--harness-config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--trial-id", default="0")
    parser.add_argument("--blender", type=Path)
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="Only generate and freeze the script; use the unified pipeline for rerun/evaluation",
    )
    args = parser.parse_args()
    try:
        tasks_root = args.tasks_root.expanduser().resolve()
        config = args.harness_config or _task_config_default(args.task, tasks_root)
        result = run(
            args.task,
            tasks_root,
            config.expanduser().resolve(),
            args.output_dir,
            args.env_file,
            args.trial_id,
            args.blender,
            execute=not args.no_execute,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(f"[l1-harness] error: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final_status"] in {"generated", "executed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
