"""Command line interface for 3DBench evaluation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.generator.task_adapter import DEFAULT_TASKS_ROOT, load_benchmark_task
from src.render.cli import _find_blender

from .core import evaluate_blender_submission
from .vlm import VLMConfig


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate one 3DBench submission.")
    parser.add_argument("--task", required=True)
    parser.add_argument("--tasks-root", type=Path, default=DEFAULT_TASKS_ROOT)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--vlm", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--eval-spec", type=Path, help="Frozen L1/L2 EvalSpec (.json or .toml)."
    )
    parser.add_argument(
        "--harness-record",
        type=Path,
        help="Trusted execution/audit record outside the submission.",
    )
    parser.add_argument("--trial-id", default="0")
    parser.add_argument("--trusted-runs-root", type=Path, help="Controller-owned L2 run root required for record import.")
    parser.add_argument("--harness-config", type=Path, help="Expected L2 Harness configuration, if overridden.")
    parser.add_argument(
        "--board", choices=("single-shot", "auto-refinement"), default=None
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    started = time.monotonic()
    try:
        task = load_benchmark_task(args.task, args.tasks_root)
        if task.level == 3:
            raise ValueError("Level 3 must be evaluated through src.ue5")
        spec_path = args.eval_spec
        if spec_path is None and task.level in {1, 2}:
            candidates = [
                task.root / "harness" / "eval_spec.json",
                task.root / "harness" / "eval_spec.toml",
            ]
            if task.level == 1:
                example_name = f"{task.task_id.split('/')[-1].lower()}"
                candidates.append(
                    Path(__file__).resolve().parent
                    / "examples"
                    / f"{example_name}.json"
                )
                if task.task_id.endswith("CodeEdit"):
                    candidates.append(
                        Path(__file__).resolve().parent / "examples" / "code_edit.json"
                    )
            for candidate in candidates:
                if candidate.is_file():
                    spec_path = candidate
                    break
            if spec_path is None and task.level == 2:
                raise ValueError(
                    f"L2 task {task.task_id} has no task-owned EvalSpec; "
                    "add harness/eval_spec.json or pass --eval-spec explicitly"
                )
        if spec_path is not None:
            from .spec import EvalSpec

            if args.vlm:
                raise ValueError(
                    "Frozen VLM ratings must be supplied in the harness record; live --vlm is a pilot option"
                )
            spec = EvalSpec.load(spec_path)
            record = None
            if args.harness_record is not None:
                record_path = args.harness_record.expanduser().resolve()
                if record_path.is_relative_to(args.submission.expanduser().resolve()):
                    raise ValueError(
                        "The harness record must be outside the submission directory"
                    )
                record = json.loads(record_path.read_text(encoding="utf-8"))
            if spec.profile == "L1":
                from .l1_budget import DeadlineBudget
                from .l1_runner import evaluate_l1_submission

                report = evaluate_l1_submission(
                    spec,
                    args.submission,
                    args.blender,
                    assets_root=task.root,
                    harness_record=record,
                    timeout=args.timeout,
                    task_id=task.task_id,
                    trial_id=args.trial_id,
                    board=args.board or "single-shot",
                    deadline=DeadlineBudget.start(args.timeout, started=started).deadline,
                )
            elif spec.profile == "L2":
                from .l2_runner import evaluate_l2_submission

                report = evaluate_l2_submission(
                    spec,
                    args.submission,
                    Path(_find_blender(args.blender)),
                    assets_root=task.root,
                    harness_record=record,
                    timeout=args.timeout,
                    task_id=task.task_id,
                    trial_id=args.trial_id,
                    board=args.board,
                    record_path=args.harness_record,
                    trusted_runs_root=args.trusted_runs_root,
                    harness_config=args.harness_config,
                )
            else:  # pragma: no cover - EvalSpec validates this
                raise ValueError(f"Unsupported evaluator profile: {spec.profile}")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["case_pass"] else 1
        if args.harness_record is not None:
            raise ValueError("--harness-record requires an EvalSpec")
        print(
            "[evaluator] No EvalSpec: using the legacy pilot diagnostic, not an L1/L2 leaderboard score.",
            file=sys.stderr,
        )
        blender = Path(_find_blender(args.blender))
        vlm = VLMConfig.from_env(args.env_file) if args.vlm else None
        report = evaluate_blender_submission(
            task,
            args.submission,
            blender,
            timeout=args.timeout,
            vlm_config=vlm,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "passed" else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[evaluator] error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
