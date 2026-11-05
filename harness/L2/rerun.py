"""Execute existing L2 code, audit each seed, bind a trusted record and evaluate."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import time
from pathlib import Path

from harness.common.attempt_log import sha256, write_json
from src.evaluator.l2_runner import evaluate_l2_submission
from src.evaluator.l2 import score_l2
from src.evaluator.spec import L2_EVALUATOR_VERSION, EvalSpec
from src.generator.task_adapter import load_benchmark_task
from src.render.cli import _find_blender

from .audit import AUDIT_VERSION, artifact_state, compare_images, record_digest, regular_file, scene_audit
from .config import load_policy
from .executor import run_process, sandbox_command
from .headless import graphics_identity

HERE = Path(__file__).resolve().parent
INSPECTOR = Path(__file__).resolve().parents[2] / "src/evaluator/l2_blender.py"


def task_paths(task):
    config = task.root / "harness/harness.toml"
    for suffix in ("json", "toml"):
        path = task.root / "harness" / f"eval_spec.{suffix}"
        if path.is_file():
            spec = EvalSpec.load(path)
            if spec.profile != "L2":
                raise ValueError("L2 harness requires an L2 EvalSpec")
            return config, path, spec
    raise ValueError("Task-owned L2 EvalSpec is required")


def inspect(blender, workspace, directory, scene, policy, timeout, *, render=False, cancel_event=None):
    directory.mkdir(parents=True, exist_ok=True)
    args = ["--scene", scene, "--output", "/audit/facts.json"]
    files = {"/l2_blender.py": INSPECTOR}
    if render:
        views = directory.parent / "views.json"
        write_json(views, list(policy.views))
        args += ["--views", "/views.json"]
        files["/views.json"] = views
    command = sandbox_command(blender, workspace, HERE / "audit_worker.py", args,
                              readonly=True, output=directory, extra_files=files, threads=policy.threads)
    execution = run_process(command, cwd=workspace, logs=directory.parent / (directory.name + "-logs"), timeout=timeout, cancel_event=cancel_event)
    process_record = directory.parent / (directory.name + "-logs") / "process.json"
    process_record.parent.mkdir(parents=True, exist_ok=True)
    write_json(process_record, execution.to_dict())
    if execution.status != "success":
        raise RuntimeError(f"Blender inspection/render: {execution.status} ({execution.return_code})")
    return json.loads((directory / "facts.json").read_text())


def rerun_submission(task_id: str, tasks_root: Path, submission: Path, output_dir: Path, *,
                     config_path: Path | None = None, trial_id: str = "rerun", blender: Path | None = None,
                     timeout: float | None = None, evaluate: bool = True,
                     generation_record: dict | None = None, prior_costs: dict | None = None,
                     evaluation_kind: str = "replay") -> dict:
    if evaluation_kind not in {"replay", "generation"}:
        raise ValueError("Invalid L2 execution kind")
    task = load_benchmark_task(task_id, tasks_root)
    if task.level != 2:
        raise ValueError("L2 harness only accepts L2 tasks")
    task.validate_materialized_assets()
    default_config, spec_path, spec = task_paths(task)
    config_path = (config_path or default_config).resolve()
    policy = load_policy(config_path, task.task_id, spec)
    task_inputs = tuple(path.as_posix() for path in task.environment_files)
    if policy.environment_files != task_inputs:
        raise ValueError("Harness environment_files do not match task allowlist")
    if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
        raise ValueError("timeout must be positive and finite")
    per_process = min(timeout, policy.timeout_steps[-1]) if timeout is not None else policy.timeout
    total_budget = max(policy.total, per_process * (len(spec.seeds) * 3 + 1))
    source = submission.expanduser().absolute()
    if source.is_symlink():
        raise ValueError("Submission cannot be a symlink")
    source_error = None
    try:
        solution = regular_file(source, "solution.py") if source.is_dir() else regular_file(source.parent, source.name)
        if solution.name != "solution.py":
            raise ValueError("Expected solution.py; reference scene bundles do not prove execution")
        code = solution.read_bytes()  # Freeze code once, before executing any seed.
    except (OSError, ValueError) as error:
        source_error = str(error)
        code = b""
    import hashlib
    code_hash = hashlib.sha256(code).hexdigest()
    blender = Path(_find_blender(blender)).resolve()
    graphics = graphics_identity()  # Fail before staging/launching seeds if Mesa EGL is missing.
    output_dir = output_dir.expanduser().resolve()
    if output_dir == source.resolve() or output_dir.is_relative_to(source.resolve()):
        raise ValueError("Trusted output directory must be outside the source submission")
    # User-provided trial labels never become filesystem path components.
    run_id = f"{task.output_slug}__{time.time_ns()}"
    run_dir = output_dir / "harness" / run_id
    run_dir.mkdir(parents=True)
    canonical = run_dir / "submission"
    canonical.mkdir()
    trusted = run_dir / "evidence"
    trusted.mkdir()
    (trusted / "solution.py").write_bytes(code)
    shutil.copy2(spec_path, trusted / spec_path.name)
    shutil.copy2(config_path, trusted / "harness.toml")
    if policy.requirements_path:
        shutil.copy2(policy.requirements_path, trusted / "requirements.json")
    started = time.monotonic()
    def remaining():
        return min(per_process, max(0, total_budget - (time.monotonic() - started)))
    inputs = {p.as_posix(): sha256(task.environment_dir / p) for p in task.environment_files}
    baseline = None
    baseline_error = None
    if spec.baseline_scene and source_error is None:
        baseline_root = run_dir / "baseline-input"
        baseline_root.mkdir()
        # No solution/ directory is staged; only the model-visible baseline is allowed.
        base_path = task.root / spec.baseline_scene
        if not base_path.resolve().is_relative_to(task.environment_dir.resolve()):
            raise ValueError("Baseline must be an allowed environment asset")
        if base_path.relative_to(task.environment_dir).as_posix() not in inputs:
            raise ValueError("Baseline is not in task environment allowlist")
        shutil.copy2(base_path, baseline_root / "baseline.blend")
        try:
            baseline = inspect(blender, baseline_root, trusted / "baseline", "/work/baseline.blend", policy, remaining())
        except (OSError, ValueError, RuntimeError) as error:
            baseline_error = str(error)
    runs = {}
    for seed in spec.seeds:
        workspace = run_dir / "seed_runs" / str(seed) / "workspace"
        workspace.mkdir(parents=True)
        task.stage_environment(workspace)
        (workspace / "solution.py").write_bytes(code)
        evidence_dir = trusted / str(seed)
        evidence_dir.mkdir()
        command = sandbox_command(blender, workspace, HERE / "execute_worker.py", [], seed=seed, threads=policy.threads)
        if source_error:
            from .executor import Execution
            execution = Execution("invalid_submission", None, 0, "MISSING_SOLUTION")
        else:
            execution = run_process(command, cwd=workspace, logs=evidence_dir / "execution", timeout=remaining())
        artifacts, failures = artifact_state(workspace, spec.required_artifacts, policy.views)
        hashes = {name: item["sha256"] for name, item in artifacts.items()}
        input_stable = all(sha256(regular_file(workspace, n)) == h for n, h in inputs.items())
        code_stable = hashes.get("solution.py") == code_hash
        result = {"passed": False, "execution": execution.to_dict(), "artifact_sha256": hashes,
                  "artifacts": artifacts, "validation_errors": failures, "scene_loadable": False,
                  "input_unchanged": input_stable, "code_unchanged": code_stable,
                  "audit": {"version": AUDIT_VERSION, "passed": False, "failures": ["not_run"]},
                  "rerender": {}, "isolation": "bubblewrap", "seed": seed}
        if source_error:
            result["validation_errors"].append(source_error)
        if baseline_error:
            result["baseline_error"] = baseline_error
        if execution.status == "success" and not failures and input_stable and code_stable:
            try:
                facts = inspect(blender, workspace, evidence_dir / "inspect", "/work/" + spec.scene, policy, remaining())
                result["scene_loadable"] = facts["scene"].get("has_real_geometry") is True
                result["audit"] = scene_audit(facts, baseline, edit=spec.mode == "edit")
                if result["audit"]["passed"]:
                    inspect(blender, workspace, evidence_dir / "rerender", "/work/" + spec.scene,
                            policy, remaining(), render=True)
                    for view in policy.views:
                        name = view["artifact"]
                        result["rerender"][name] = compare_images(workspace / name, evidence_dir / "rerender" / name,
                                                                 policy.mean_error, policy.p99_error)
            except (OSError, ValueError, RuntimeError) as error:
                result["validation_errors"].append(str(error))
        result["inspection_processes"] = {p.parent.name: json.loads(p.read_text())
            for p in evidence_dir.glob("*-logs/process.json")}
        result["execution_passed"] = (execution.status == "success" and not failures
                                       and input_stable and code_stable and result["scene_loadable"])
        stable = all(sha256(regular_file(workspace, n)) == h for n, h in hashes.items())
        if not stable:
            result["validation_errors"].append("Artifact changed after validation")
        if not result["execution_passed"] and execution.status == "success":
            result["validation_errors"].append("Candidate process completed but required execution validation did not pass")
        result["artifacts_unchanged"] = stable
        result["integrity_passed"] = bool(result["execution_passed"] and stable and result["audit"]["passed"]
            and len(result["rerender"]) == len(policy.views) and all(v["passed"] for v in result["rerender"].values()))
        result["passed"] = result["execution_passed"] and result["integrity_passed"]
        runs[str(seed)] = result
        write_json(evidence_dir / "result.json", result)
        if seed == spec.seeds[0]:
            task.stage_environment(canonical)
            for name in hashes:
                destination = canonical / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(regular_file(workspace, name), destination)
    canonical_artifacts, canonical_errors = artifact_state(canonical, spec.required_artifacts, policy.views)
    canonical_hashes = {n: item["sha256"] for n, item in canonical_artifacts.items()}
    first = runs[str(spec.seeds[0])]
    bound = canonical_hashes == first["artifact_sha256"] and not canonical_errors
    for seed, seed_result in runs.items():
        facts_path = trusted/seed/'inspect/facts.json'
        seed_result.update(quality_evaluated=False, quality_passed=False, quality_score=None)
        if seed_result['execution_passed'] and facts_path.is_file():
            facts = json.loads(facts_path.read_text())
            seed_workspace = run_dir/'seed_runs'/seed/'workspace'
            facts['artifacts'] = {name: {**value, 'loadable': True, 'path': str(seed_workspace/name)}
                                  for name, value in seed_result['artifacts'].items()}
            facts['harness'] = {'execution_passed': seed_result['execution_passed'],
                                'integrity_passed': seed_result['integrity_passed'], 'seed_runs': runs}
            if baseline:
                facts['baseline'] = baseline['scene']
            facts['reference_images'] = {view: {'path': str(task.root/path)} for view,path in spec.reference_images.items()}
            quality = score_l2(spec, facts)
            seed_result.update(quality_evaluated=True, quality_passed=quality['task_quality_pass'],
                quality_score=sum(m['weight']*m['score'] for name,m in quality['modules'].items() if name!='robust')/.9,
                quality_failed_gates=[name for name,g in quality['gates'].items() if not g['passed']
                    and name not in {'execution','integrity','all_seeds','all_seed_quality'}])
        write_json(trusted/seed/'result.json', seed_result)
    record = {"schema_version": 3, "harness_version": policy.version, "evaluator_version": L2_EVALUATOR_VERSION,
              "task_id": task.task_id, "trial_id": trial_id, "run_id": run_id, "spec_sha256": spec.digest,
              "harness_config_sha256": policy.digest, "artifact_sha256": canonical_hashes,
              "source_code_sha256": code_hash, "input_sha256": inputs, "canonical_seed": spec.seeds[0],
              "generation_passed": generation_record.get("generation_passed") if generation_record else None,
              "generation": generation_record, "execution_passed": bool(bound and all(v["execution_passed"] for v in runs.values())),
              "integrity_passed": bool(bound and all(v["integrity_passed"] for v in runs.values())), "integrity_version": AUDIT_VERSION,
              "seed_runs": runs, "total_seconds": time.monotonic() - started,
              "final_status": "verified" if bound and all(v["passed"] for v in runs.values()) else "failed",
              "evidence_sha256": {p.relative_to(run_dir).as_posix(): sha256(p) for p in trusted.rglob("*") if p.is_file()},
              "seed_protocol": "Set Python/NumPy/Cycles initial seed and expose THREEDBENCH_SEED/BENCHMARK_SEED; candidate code may explicitly reseed.",
              "blender": str(blender),
              "graphics_runtime": graphics,
              "baseline_execution": json.loads((trusted / "baseline-logs/process.json").read_text())
                  if (trusted / "baseline-logs/process.json").exists() else {},
              "execution_policy": {"timeout_seconds": per_process, "max_total_seconds": total_budget,
                                   "timeout_steps_seconds": policy.timeout_steps,
                                   "threads": policy.threads, "sandbox": "bubblewrap", "network": False}}
    from src.evaluator.l2_requirements import digest
    record['requirements_sha256'] = digest(policy.requirements) if policy.requirements else None
    record["evaluation_kind"] = evaluation_kind
    record["board"] = generation_record.get("board", "auto-refinement") if generation_record else "single-shot"
    record["generation_protocol"] = generation_record.get("protocol") if generation_record else "external-unknown"
    generation_costs = generation_record.get("costs", {}) if generation_record else {}
    record["costs"] = {**generation_costs, "execution_seconds": record["total_seconds"],
        "generation_seconds": generation_record.get("total_seconds") if generation_record else None,
        "total_seconds": record["total_seconds"] + (generation_record.get("total_seconds", 0) if generation_record else 0),
        "model_calls": None, "total_tokens": generation_costs.get("total_tokens")}
    prior_costs = prior_costs or {}
    record['costs']['execution_total_seconds'] = record['total_seconds']+prior_costs.get('execution_total_seconds', 0)
    record['costs']['evaluation_total_seconds'] = prior_costs.get('evaluation_total_seconds', 0)
    record['costs']['execution_rounds'] = prior_costs.get('execution_rounds', 0)+1
    record['costs']['total_seconds'] = (record['costs']['execution_total_seconds']
        +record['costs']['evaluation_total_seconds']+(record['costs']['generation_seconds'] or 0))
    record = json.loads(json.dumps(record, allow_nan=False))
    record["record_sha256"] = record_digest(record)
    record_path = run_dir / "harness_record.json"  # Outside /submission and all candidate mounts.
    write_json(record_path, record)
    result = {"run_dir": str(run_dir), "submission": str(canonical), "harness_record": str(record_path),
              "final_status": record["final_status"], "execution_passed": record["execution_passed"],
              "integrity_passed": record["integrity_passed"]}
    if evaluate:
        report = evaluate_l2_submission(spec, canonical, blender, assets_root=task.root,
            harness_record=record, timeout=per_process, task_id=task.task_id, trial_id=trial_id,
            record_path=record_path, trusted_runs_root=output_dir/'harness', harness_config=config_path,
            board=record["board"])
        result["report_path"] = report["report_path"]
        result["score"] = {key: report[key] for key in ("G", "S_core", "S_level", "case_pass", "errors")}
        result['costs'] = report['efficiency']
        result["evaluation_completed"] = not report["errors"]
        result["evaluation_timed_out"] = report.get("timed_out", False)
        if report["errors"]:
            result["final_status"] = "evaluation_failed"
    write_json(run_dir / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs/l2_verified"))
    parser.add_argument("--harness-config", type=Path)
    parser.add_argument("--trial-id", default="rerun")
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--no-evaluate", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = rerun_submission(args.task, args.tasks_root, args.submission, args.output_dir,
            config_path=args.harness_config, trial_id=args.trial_id, blender=args.blender,
            timeout=args.timeout, evaluate=not args.no_evaluate)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[l2-rerun] {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final_status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
