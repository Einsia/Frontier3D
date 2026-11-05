"""Generate L2 submissions, then execute and evaluate with increasing timeouts."""
import argparse
import json
from pathlib import Path

from harness.common.attempt_log import write_json
from src.generator.task_adapter import load_benchmark_task
from src.render.cli import _find_blender
from .budget import has_timeout
from .config import load_policy
from .generation import generate
from .headless import graphics_identity
from .rerun import rerun_submission, task_paths


def run_task(task_id, tasks_root, output_dir, *, config_path=None, env_file=None,
             trial_id="0", blender=None, generate_only=False, model=None, codex_binary=None):
    task = load_benchmark_task(task_id, tasks_root)
    if task.level != 2:
        raise ValueError("L2 harness only accepts L2 tasks")
    default, _, spec = task_paths(task)
    config = config_path or default
    policy = load_policy(config, task.task_id, spec)
    binary = Path(_find_blender(blender)).resolve()
    graphics_identity()
    generation = generate(task, config, policy, output_dir, binary, env_file, trial_id,
                          **({"model": model, "codex_binary": codex_binary} if model or codex_binary else {}))
    run_dir = Path(generation["run_dir"])
    record = json.loads(Path(generation["harness_record"]).read_text())
    if generate_only:
        write_json(run_dir / "result.json", generation)
        return generation
    # Missing/failed generation also produces an explicit failed execution record and report.
    rounds = []
    prior_costs = {}
    for limit in policy.timeout_steps:
        result = rerun_submission(task_id, tasks_root, run_dir / "outputs", output_dir,
            config_path=config, trial_id=trial_id, blender=binary, timeout=limit, generation_record=record,
            prior_costs=prior_costs, evaluation_kind="generation")
        prior_costs = result.get('costs', {})
        execution = json.loads(Path(result["harness_record"]).read_text())
        timed_out = has_timeout(execution) or result.get("evaluation_timed_out", False)
        rounds.append({"timeout_seconds": limit, "timed_out": timed_out, **result})
        write_json(run_dir / "execution_rounds.json", rounds)
        if not timed_out:
            break
    result.update(generation_run_dir=str(run_dir), generation_record=generation["harness_record"],
                  generation_status=generation["final_status"], execution_rounds=rounds,
                  timeout_exhausted=rounds[-1]["timed_out"])
    write_json(run_dir / "result.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task"))
    parser.add_argument("--harness-config", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs/l2_verified"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--trial-id", default="0")
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run_task(args.task, args.tasks_root, args.output_dir, config_path=args.harness_config,
            env_file=args.env_file, trial_id=args.trial_id, blender=args.blender, generate_only=args.generate_only)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[l2-harness] error: {error}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["final_status"] == ("success" if args.generate_only else "verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
