"""Bounded, auditable L1 feedback-round protocol.

The baseline remains ``single-shot``.  The optional refinement board may add
at most three rounds, each with an immutable source/artifact snapshot.  Public
feedback is deliberately coarse and cannot carry reference or private probe
payloads.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import stat
import time
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path, PurePosixPath
from typing import Any

from src.evaluator.l1_budget import BudgetExhausted, DeadlineBudget
from src.evaluator.l1_parent_io import (
    audit_directory,
    copy_regular_files,
    ensure_directory,
)
from src.evaluator.spec import EvalSpec

from .attempt_log import sha256, sha256_bytes, write_json, write_json_atomic
from .feedback import GUIDANCE, validate_public_feedback

AGENT_PROTOCOL = "l1-agent-v1"
MAX_ROUNDS = 3
_FORBIDDEN = re.compile(
    r"(?:reference|private|probe|answer|solution|vertices|faces|coordinates|mesh_payload|/scene/)",
    re.IGNORECASE,
)
_SNAPSHOT_MAX_BYTES = 512 * 1024 * 1024
_SNAPSHOT_MAX_FILES = 4096
_SNAPSHOT_MAX_DEPTH = 32
_SNAPSHOT_MAX_FILE_BYTES = 256 * 1024 * 1024
_SNAPSHOT_DEADLINE: ContextVar[float | None] = ContextVar(
    "l1_agent_snapshot_deadline", default=None
)


def _optional_seed(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer or null")
    return value


def _execution_evidence(execution: dict[str, Any]) -> dict[str, Any]:
    """Keep only auditable execution fields in a trusted refinement manifest.

    Candidate stdout/stderr and arbitrary callback payloads are intentionally
    not copied into the trusted round ledger. Only validated feedback is public.
    The selected fields are enough to
    bind retry state and the evaluator-owned RNG trace without turning the
    feedback protocol into a private-probe transport.
    """
    allowed = {
        "status",
        "error_code",
        "return_code",
        "elapsed_seconds",
        "retry_count",
        "attempt_count",
        "attempts",
        "sandbox_status",
        "rng_trace",
        "program_seed",
        "repair_round",
        "execution_binding",
        "seed_bindings",
        "workspace_guard",
        "workspace_cleanup",
    }
    evidence = {key: execution[key] for key in sorted(allowed) if key in execution}
    attempts = evidence.get("attempts")
    if isinstance(attempts, list):
        normalized_attempts: list[dict[str, Any]] = []
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            normalized_attempts.append(
                {
                    key: attempt[key]
                    for key in (
                        "attempt",
                        "status",
                        "error_code",
                        "return_code",
                        "elapsed_seconds",
                    )
                    if key in attempt
                }
            )
        evidence["attempts"] = normalized_attempts
    rng_trace = evidence.get("rng_trace")
    if rng_trace is None:
        evidence["rng_trace_status"] = "not_configured"
    elif not isinstance(rng_trace, dict):
        evidence["rng_trace"] = None
        evidence["rng_trace_status"] = "invalid"
    else:
        evidence["rng_trace_status"] = rng_trace.get("status", "unknown")
    guard = evidence.get("workspace_guard")
    if guard is not None and not isinstance(guard, dict):
        evidence["workspace_guard"] = None
        evidence["workspace_guard_status"] = "invalid"
    elif isinstance(guard, dict):
        evidence["workspace_guard_status"] = guard.get("status", "unknown")
        cleanup = guard.get("process_cleanup")
        if isinstance(cleanup, dict):
            evidence["workspace_cleanup"] = {
                key: cleanup.get(key)
                for key in (
                    "cleanup_ack",
                    "target_pid",
                    "target_remaining",
                    "descendants_remaining",
                    "descendants_zombies",
                )
                if key in cleanup
            }
    return evidence


def validate_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    """Allow only public aggregate feedback, rejecting hidden evidence fields."""
    if not isinstance(feedback, dict):
        raise TypeError("feedback must be an object")
    allowed = {"status", "failed_requirements", "public_metrics", "guidance"}
    unknown = set(feedback) - allowed
    if unknown:
        raise ValueError(f"feedback contains private or unknown fields: {sorted(unknown)}")
    status = feedback.get("status", "unavailable")
    if status not in {"passed", "failed", "unavailable", "incomplete"}:
        raise ValueError("feedback status is not public")
    failed = feedback.get("failed_requirements", [])
    if not isinstance(failed, list) or not all(
        isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,96}", item)
        for item in failed
    ):
        raise ValueError("failed_requirements must contain public requirement ids")
    metrics = feedback.get("public_metrics", {})
    if not isinstance(metrics, dict) or any(
        not isinstance(key, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", key)
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        for key, value in metrics.items()
    ):
        raise ValueError("public_metrics must be a numeric aggregate map")
    guidance = feedback.get("guidance", "")
    if not isinstance(guidance, str) or len(guidance) > 2000:
        raise ValueError("guidance must be a bounded public string")
    if _FORBIDDEN.search(guidance):
        raise ValueError("guidance appears to contain hidden reference/probe data")
    normalized = {
        "status": status,
        "failed_requirements": list(failed),
        "public_metrics": {key: float(value) for key, value in metrics.items()},
        "guidance": guidance,
    }
    json.dumps(normalized, allow_nan=False)
    return normalized


def _snapshot_deadline(value: float | None = None) -> float:
    active = value if value is not None else _SNAPSHOT_DEADLINE.get()
    if active is not None:
        # Parent-I/O workers have an independent real monotonic clock.  The
        # translation keeps normal deadlines unchanged while allowing tests
        # (and adapters that inject a logical clock) to retain the same
        # remaining allowance without confusing the worker receipt.
        remaining = active - time.monotonic()
        if abs(active - time.perf_counter()) > 100_000:
            return time.perf_counter() + max(0.0, remaining)
        return active
    return time.perf_counter() + 300.0


def _snapshot_tree(source: Path, destination: Path, *, deadline: float | None = None) -> dict[str, dict[str, Any]]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise ValueError("agent source snapshot must be a directory")
    io_deadline = _snapshot_deadline(deadline)
    candidates: list[tuple[Path, PurePosixPath, int]] = []
    total = 0
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in {"agent_rounds", "evaluation"} for part in relative.parts):
            continue
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"agent source snapshot contains symlink: {relative}")
        if stat.S_ISDIR(info.st_mode):
            if len(relative.parts) > _SNAPSHOT_MAX_DEPTH:
                raise ValueError("agent source snapshot directory depth limit exceeded")
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"agent source snapshot contains nonregular entry: {relative}")
        if len(candidates) >= _SNAPSHOT_MAX_FILES:
            raise ValueError("agent source snapshot file limit exceeded")
        if info.st_size > _SNAPSHOT_MAX_FILE_BYTES:
            raise ValueError("agent source snapshot single-file limit exceeded")
        total += info.st_size
        if total > _SNAPSHOT_MAX_BYTES:
            raise ValueError("agent source snapshot byte limit exceeded")
        candidates.append((path, relative, info.st_size))
    hashes: dict[str, dict[str, Any]] = {}
    # A very small remaining allowance cannot safely pay for a new worker
    # process.  Keep the existing terminal-budget semantics while still
    # enforcing the same quota checks for this tiny bounded copy path.
    if io_deadline - time.monotonic() < 0.1:
        destination.mkdir(parents=True, exist_ok=True)
        copied_total = 0
        for path, relative, _size in candidates:
            if time.monotonic() >= io_deadline:
                raise BudgetExhausted("Agent snapshot exhausted shared deadline")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            info = target.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise ValueError(f"agent source snapshot copy is not regular: {relative}")
            copied_total += info.st_size
            if info.st_size > _SNAPSHOT_MAX_FILE_BYTES or copied_total > _SNAPSHOT_MAX_BYTES:
                raise ValueError("agent source snapshot copy quota exceeded")
            hashes[relative.as_posix()] = {
                "sha256": sha256(target),
                "bytes": info.st_size,
            }
        return hashes
    ensure_directory(destination, deadline=io_deadline, parents=True)
    remaining = _SNAPSHOT_MAX_BYTES
    for path, relative, size in candidates:
        receipt = copy_regular_files(
            path.parent,
            destination,
            (path.name,),
            target_files=(relative.as_posix(),),
            deadline=io_deadline,
            max_bytes=max(1, remaining),
        )
        row = receipt["result"]["files"][0]
        hashes[relative.as_posix()] = {"sha256": row["sha256"], "bytes": row["bytes"]}
        remaining -= size
    return hashes


def _audit_snapshot_quota(destination: Path, *, deadline: float) -> dict[str, Any]:
    """Recheck an immutable round snapshot through the bounded worker."""
    receipt = audit_directory(
        destination,
        deadline=_snapshot_deadline(deadline),
        max_bytes=_SNAPSHOT_MAX_BYTES,
        max_files=_SNAPSHOT_MAX_FILES,
        max_depth=_SNAPSHOT_MAX_DEPTH,
        max_file_bytes=_SNAPSHOT_MAX_FILE_BYTES,
    )
    return {"status": "completed", **receipt["result"]}


def _snapshot_with_deadline(source: Path, destination: Path, deadline: float) -> dict[str, dict[str, Any]]:
    token = _SNAPSHOT_DEADLINE.set(deadline)
    try:
        return _snapshot_tree(source, destination)
    finally:
        _SNAPSHOT_DEADLINE.reset(token)


def _copy_artifact(path: Path, target: Path, *, deadline: float | None = None) -> dict[str, Any]:
    path = path.expanduser().absolute()
    target = target.absolute()
    receipt = copy_regular_files(
        path.parent,
        target.parent,
        (path.name,),
        target_files=(target.name,),
        deadline=_snapshot_deadline(deadline),
        max_bytes=_SNAPSHOT_MAX_FILE_BYTES,
    )
    return receipt["result"]["files"][0]


def _publish_round_index(root: Path, manifest: dict[str, Any], round_index: int) -> dict[str, Any]:
    """Append one immutable, reloadable round entry without rewriting history."""
    index_path = root / "agent_rounds" / "index.json"
    if index_path.is_symlink() or (index_path.exists() and not index_path.is_file()):
        raise ValueError("agent round index is not a regular file")
    if index_path.is_file():
        if index_path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("agent round index exceeds bounded size")
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError("agent round index is not reloadable") from error
        if not isinstance(index, dict) or index.get("protocol") != "l1-agent-round-index-v1":
            raise ValueError("agent round index protocol mismatch")
        entries = index.get("rounds")
        if not isinstance(entries, list):
            raise ValueError("agent round index rounds must be a list")
    else:
        index = {"protocol": "l1-agent-round-index-v1", "status": "recorded", "rounds": []}
        entries = index["rounds"]
    if any(isinstance(item, dict) and item.get("round") == round_index for item in entries):
        raise FileExistsError(f"agent round index already contains round {round_index}")
    manifest_path = root / "agent_rounds" / f"round-{round_index:02d}" / "round_manifest.json"
    entries.append({
        "round": round_index,
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "source_snapshot_sha256": manifest["round_provenance"]["source_snapshot_sha256"],
        "artifact_snapshot_sha256": manifest["round_provenance"]["artifact_snapshot_sha256"],
        "feedback_status": manifest["feedback"]["status"],
        "rng_trace_status": manifest["round_provenance"].get("rng_trace_status", "not_configured"),
    })
    write_json_atomic(index_path, index)
    return {"path": str(index_path), "sha256": sha256(index_path), "round": round_index}


def record_round(
    run_dir: Path,
    round_index: int,
    source_dir: Path,
    *,
    artifacts: dict[str, Path] | None = None,
    feedback: dict[str, Any] | None = None,
    costs: dict[str, Any] | None = None,
    board: str = "auto-refinement",
    repair_round: int | None = None,
    program_seed: int | None = None,
    execution_evidence: dict[str, Any] | None = None,
    snapshot_quota: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Persist an immutable trusted round; only feedback.json is public."""
    if board not in {"single-shot", "auto-refinement"}:
        raise ValueError("unknown agent board")
    if type(round_index) is not int or round_index < 0 or round_index >= MAX_ROUNDS:
        raise ValueError(f"round_index must be between 0 and {MAX_ROUNDS - 1}")
    if board == "single-shot" and round_index != 0:
        raise ValueError("single-shot board cannot record a second round")
    repair_round = _optional_seed(repair_round, "repair_round")
    if repair_round is not None and repair_round != round_index:
        raise ValueError("repair_round must equal the recorded round_index")
    program_seed = _optional_seed(program_seed, "program_seed")
    public_feedback = validate_feedback(feedback or {"status": "unavailable"})
    round_dir = run_dir / "agent_rounds" / f"round-{round_index:02d}"
    if round_dir.exists():
        raise FileExistsError(f"agent round already exists: {round_dir}")
    source_hashes = _snapshot_tree(source_dir, round_dir / "source", deadline=deadline)
    artifact_hashes: dict[str, dict[str, Any]] = {}
    for name, path in (artifacts or {}).items():
        relative = PurePosixPath(name) if isinstance(name, str) else None
        if (
            relative is None
            or not relative.parts
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ValueError("artifact names must be relative")
        path = Path(path).expanduser().absolute()
        if not path.is_file() or any(part.is_symlink() for part in (path, *path.parents)):
            raise ValueError(f"agent artifact is missing or symlinked: {name}")
        target = round_dir / "artifacts" / Path(*relative.parts)
        row = _copy_artifact(path, target, deadline=deadline)
        artifact_hashes[name] = {"sha256": row["sha256"], "bytes": row["bytes"]}
    safe_costs = dict(costs or {})
    for value in safe_costs.values():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("agent costs must be finite or null")
    source_snapshot_sha256 = sha256_bytes(
        json.dumps(source_hashes, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    artifact_snapshot_sha256 = sha256_bytes(
        json.dumps(artifact_hashes, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    safe_execution = _execution_evidence(execution_evidence or {})
    rng_trace = safe_execution.get("rng_trace")
    if isinstance(rng_trace, dict):
        # Keep a separate immutable file so later reports can cite the exact
        # trace without parsing the whole round manifest.
        write_json(round_dir / "rng_trace.json", rng_trace)
    manifest = {
        "protocol": AGENT_PROTOCOL,
        "board": board,
        "round": round_index,
        "source": source_hashes,
        "artifacts": artifact_hashes,
        "feedback": public_feedback,
        "feedback_sha256": sha256(
            round_dir / "feedback.json"
        )
        if (round_dir / "feedback.json").is_file()
        else None,
        "costs": safe_costs,
        "round_provenance": {
            "repair_round": repair_round,
            "program_seed": program_seed,
            "source_snapshot_sha256": source_snapshot_sha256,
            "artifact_snapshot_sha256": artifact_snapshot_sha256,
            "execution": safe_execution,
            "rng_trace_path": "rng_trace.json" if isinstance(rng_trace, dict) else None,
            "rng_trace_status": safe_execution.get("rng_trace_status", "not_configured"),
            "snapshot_quota": dict(snapshot_quota) if isinstance(snapshot_quota, dict) else None,
        },
    }
    write_json(round_dir / "feedback.json", public_feedback)
    manifest["feedback_sha256"] = sha256(round_dir / "feedback.json")
    write_json(round_dir / "round_manifest.json", manifest)
    return manifest


def run_refinement(
    run_dir: Path,
    source_dir: Path,
    *,
    generate_round: Callable[[int, Path, dict[str, Any], float], dict[str, Any]],
    execute_round: Callable[[Path, float], dict[str, Any]],
    feedback_round: Callable[[int, dict[str, Any]], dict[str, Any]],
    max_rounds: int = MAX_ROUNDS,
    max_total_seconds: float = 900.0,
    deadline: float | None = None,
    feedback_spec: EvalSpec | None = None,
) -> dict[str, Any]:
    """Run the bounded, public-feedback refinement protocol.

    ``generate_round`` is the adapter boundary for a Codex/model service; it
    receives only the staged source and the previous *public* feedback.  The
    A durable trusted checkpoint surrounds each callback. Children must inherit
    the same absolute deadline in a production adapter; opaque Python callbacks
    remain cooperative, not forcibly preemptible. Late success is never accepted.
    Model-service adapters must supply feedback_spec to enforce the frozen ID
    and guidance allowlist. Legacy callbacks retain only shape validation.
    """
    if type(max_rounds) is not int or not 1 <= max_rounds <= MAX_ROUNDS:
        raise ValueError(f"max_rounds must be between 1 and {MAX_ROUNDS}")
    if isinstance(max_total_seconds, bool) or not isinstance(
        max_total_seconds, (int, float)
    ) or not math.isfinite(max_total_seconds) or max_total_seconds <= 0:
        raise ValueError("max_total_seconds must be a positive finite number")
    budget = DeadlineBudget.start(max_total_seconds, deadline=deadline)
    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("refinement source_dir must be a directory")
    root = Path(run_dir).expanduser().resolve()
    if root.is_relative_to(source):
        raise ValueError("agent run directory must be outside the submission source")
    root.mkdir(parents=True, exist_ok=True)
    started = budget.started
    state_path = root / "agent_state.json"
    if state_path.exists():
        raise FileExistsError(f"agent run already exists: {state_path}")
    state: dict[str, Any] = {
        "protocol": "l1-agent-state-v1", "board": "auto-refinement",
        "status": "running", "phase": "initializing", "rounds": [],
        "callback_interruptibility": "cooperative_adapter_must_forward_absolute_deadline",
    }

    def _adapter_workspace_guard(execution: dict[str, Any]) -> dict[str, Any] | None:
        """Extract the bounded candidate guard receipt from an adapter result."""
        if not isinstance(execution, dict):
            return None
        value = execution.get("workspace_guard")
        return value if isinstance(value, dict) else None

    def checkpoint(status: str, phase: str) -> None:
        state.update(status=status, phase=phase, budget=budget.record("agent"))
        write_json_atomic(state_path, state)

    checkpoint("running", "initializing")
    def public_feedback(value: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_feedback(value)
        return validate_public_feedback(normalized, feedback_spec) if feedback_spec is not None else normalized

    previous_feedback = public_feedback({"status": "unavailable", "guidance": GUIDANCE['unavailable']})
    state['feedback_policy'] = 'frozen_allowlist' if feedback_spec is not None else 'legacy_callback_shape_only'
    state['feedback_spec_sha256'] = feedback_spec.digest if feedback_spec is not None else None
    rounds: list[dict[str, Any]] = []
    current_source = source
    final_status = "incomplete"

    for round_index in range(max_rounds):
        if budget.exhausted:
            final_status = "budget_exhausted"
            break
        work = root / "agent_work" / f"round-{round_index:02d}"
        work_source = work / "source"
        if work.exists():
            raise FileExistsError(f"refinement work directory already exists: {work}")
        row: dict[str, Any] = {"round": round_index, "repair_round": round_index,
                               "source": str(work_source), "status": "running", "phase": "staging",
                               "accepted": False}
        state["rounds"].append(row)
        generation: dict[str, Any] = {"status": "not_run"}
        execution: dict[str, Any] = {"status": "not_run"}
        feedback = public_feedback({"status": "unavailable", "guidance": GUIDANCE['unavailable']})
        program_seed = None
        manifest = None
        phase = "staging"
        pending_error: BaseException | None = None
        artifacts: dict[str, Path] = {}
        costs: dict[str, Any] = {}
        try:
            checkpoint("running", phase)
            budget.check()
            work_source.mkdir(parents=True)
            snapshot_hashes = _snapshot_with_deadline(
                current_source, work_source, budget.deadline
            )
            # Do not launch another subprocess when only a tiny shared-budget
            # allowance remains.  Starting parent-I/O at this point can mask
            # the authoritative late-callback/budget-exhausted result, while
            # the bounded snapshot itself has already been recorded.
            if budget.exhausted or budget.remaining < 0.1:
                row["snapshot_quota"] = {
                    "status": "not_measurable",
                    "reason": (
                        "shared deadline exhausted after snapshot"
                        if budget.exhausted
                        else "insufficient shared allowance for quota audit"
                    ),
                }
            else:
                row["snapshot_quota"] = _audit_snapshot_quota(
                    work_source, deadline=budget.deadline
                )
            if row["snapshot_quota"].get("status") != "not_measurable":
                row["snapshot_quota"]["snapshot_digest"] = sha256_bytes(
                    json.dumps(snapshot_hashes, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                )
            budget.check()
            phase = row["phase"] = "generation"
            checkpoint("running", phase)
            budget.check()
            generation = generate_round(round_index, work_source, previous_feedback, budget.remaining)
            if not isinstance(generation, dict):
                raise TypeError("Round adapter returned a non-object")
            row["generation_status"] = generation.get("status")
            repair_round = _optional_seed(generation.get("repair_round", round_index), "repair_round")
            if repair_round != round_index:
                raise ValueError(f"repair_round must equal scheduler round {round_index}, got {repair_round}")
            program_seed = _optional_seed(generation.get("program_seed"), "program_seed")
            artifacts = generation.get("artifacts", {})
            costs = generation.get("costs", {})
            if not isinstance(artifacts, dict) or not isinstance(costs, dict):
                raise TypeError("Round artifacts and costs must be objects")
            budget.check()
            if generation.get("status") == "success":
                phase = row["phase"] = "execution"
                checkpoint("running", phase)
                budget.check()
                execution = execute_round(work_source, budget.remaining)
                if not isinstance(execution, dict):
                    raise TypeError("Executor returned a non-object")
                guard = _adapter_workspace_guard(execution)
                if guard is not None:
                    row["workspace_guard"] = guard
                    cleanup = guard.get("process_cleanup")
                    if isinstance(cleanup, dict):
                        row["workspace_cleanup"] = {
                            key: cleanup.get(key)
                            for key in (
                                "cleanup_ack",
                                "target_pid",
                                "target_remaining",
                                "descendants_remaining",
                                "descendants_zombies",
                            )
                            if key in cleanup
                        }
                    if guard.get("status") in {"quota_exceeded", "deadline_exhausted"}:
                        raise BudgetExhausted(
                            "Agent adapter workspace guard exhausted the shared budget"
                        )
                    if isinstance(cleanup, dict) and cleanup.get("cleanup_ack") is False:
                        raise RuntimeError("Agent adapter workspace cleanup was not acknowledged")
                row["execution_status"] = execution.get("status")
                observed_round = _optional_seed(execution.get("repair_round", round_index), "repair_round")
                if observed_round != round_index:
                    raise ValueError("Execution repair_round does not match scheduler round")
                observed_seed = _optional_seed(execution.get("program_seed"), "program_seed")
                if program_seed is not None and observed_seed is not None and program_seed != observed_seed:
                    raise ValueError("Execution program_seed does not match generation")
                if program_seed is None:
                    program_seed = observed_seed
                budget.check()
                phase = row["phase"] = "feedback"
                checkpoint("running", phase)
                budget.check()
                feedback = public_feedback(feedback_round(round_index, execution))
                budget.check()
                if feedback["status"] == "passed" and execution.get("status") not in {
                    "success", "executed", "evaluated", "scored",
                }:
                    raise ValueError("Passed feedback cannot override unsuccessful execution")
            else:
                execution = {"status": "not_run", "generation_status": generation.get("status")}
                feedback = public_feedback({"status": "unavailable", "guidance": GUIDANCE['unavailable']})
        except (Exception, KeyboardInterrupt, SystemExit) as error:  # noqa: BLE001 - checkpoint then re-raise, except budget
            pending_error = error
            final_status = "budget_exhausted" if isinstance(error, BudgetExhausted) else (
                "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed")
            row.update(status=final_status, failed_phase=phase, exception_type=type(error).__name__)
            feedback = public_feedback({"status": "unavailable", "guidance": GUIDANCE['unavailable']})
            checkpoint(final_status, phase)
        # Snapshot/ledger writes are cleanup after exhaustion, never fresh work.
        try:
            phase = "persisting"
            row["phase"] = phase
            checkpoint(final_status if pending_error else "running", phase)
            if work_source.is_dir():
                manifest = record_round(
                    root, round_index, work_source,
                    artifacts=artifacts if isinstance(artifacts, dict) else {},
                    feedback=feedback,
                    costs={**(costs if isinstance(costs, dict) else {}),
                           "execution": execution, "elapsed_seconds": time.monotonic() - started},
                    repair_round=round_index, program_seed=program_seed,
                    execution_evidence=execution if isinstance(execution, dict) else {},
                    snapshot_quota=row.get("snapshot_quota"),
                    deadline=budget.deadline,
                )
                index_receipt = _publish_round_index(root, manifest, round_index)
                row["manifest"] = str(root / "agent_rounds" / f"round-{round_index:02d}" / "round_manifest.json")
                row["manifest_sha256"] = sha256(Path(row["manifest"]))
                row["round_index"] = index_receipt
            if pending_error is None and budget.exhausted:
                pending_error = BudgetExhausted("Agent persistence exceeded shared deadline")
                final_status = "budget_exhausted"
                row.update(status=final_status, failed_phase=phase, exception_type="BudgetExhausted")
        except (Exception, KeyboardInterrupt, SystemExit) as error:  # noqa: BLE001 - preserve original failure and checkpoint
            row["persistence_exception_type"] = type(error).__name__
            if pending_error is None:
                pending_error = error
                final_status = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
                row.update(status=final_status, failed_phase=phase, exception_type=type(error).__name__)
        rounds.append(
            {
                "round": round_index,
                "generation": generation,
                "execution": execution,
                "feedback": feedback,
                "manifest": manifest,
            }
        )
        if pending_error is not None:
            checkpoint(final_status, row.get("failed_phase", phase))
            if isinstance(pending_error, BudgetExhausted):
                break
            raise pending_error
        row.update(status="completed", phase="completed", accepted=True)
        checkpoint("running", "round_completed")
        previous_feedback = feedback
        current_source = work_source
        if feedback["status"] == "passed":
            final_status = "passed"
            break
        final_status = "incomplete"

    checkpoint(final_status, "completed")
    if budget.exhausted and final_status != "budget_exhausted":
        final_status = "budget_exhausted"
        if state["rounds"]:
            state["rounds"][-1].update(status=final_status, accepted=False)
        checkpoint(final_status, "completed")
    return {
        "protocol": AGENT_PROTOCOL,
        "board": "auto-refinement",
        "status": final_status,
        "rounds": rounds,
        "round_count": len(rounds),
        "max_rounds": max_rounds,
        "max_total_seconds": float(max_total_seconds),
        "elapsed_seconds": time.monotonic() - started,
        "budget_exhausted": final_status == "budget_exhausted",
        "budget": budget.record("agent"),
        "state_path": str(state_path),
    }


__all__ = [
    "AGENT_PROTOCOL",
    "MAX_ROUNDS",
    "record_round",
    "run_refinement",
    "validate_feedback",
]
