"""Command-line interface for the two bpy script generation tasks."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from .client import (
    BpyScriptGenerator,
    GeneratorConfig,
    GeneratorError,
    resolve_output_path,
    write_script,
)
from .task_adapter import (
    DEFAULT_TASKS_ROOT,
    default_task_run_dir,
    generate_task_submission,
    load_benchmark_task,
)


def _provider_parser() -> argparse.ArgumentParser:
    provider = argparse.ArgumentParser(add_help=False)
    provider.add_argument(
        "--model",
        help="Model override; defaults to OPENAI_MODEL from .env.",
    )
    provider.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Environment file (default: repository .env).",
    )
    provider.add_argument(
        "--runtime",
        choices=("local", "docker"),
        help="Native generator runtime; overrides GENERATOR_RUNTIME from .env.",
    )
    provider.add_argument(
        "--timeout",
        type=float,
        help="Per-native-invocation timeout in seconds; overrides GENERATOR_TIMEOUT.",
    )
    provider.add_argument(
        "--max-attempts",
        type=int,
        help="Transport/syntax attempts; overrides GENERATOR_MAX_ATTEMPTS.",
    )
    provider.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "max"),
        help="Native model reasoning effort override.",
    )
    return provider


def _direct_common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(
        add_help=False,
        parents=[_provider_parser()],
    )
    common.add_argument(
        "--output",
        required=True,
        metavar="NAME.py",
        help="Output filename under data/output_script (paths are not accepted).",
    )
    common.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing an existing output script.",
    )
    return common


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate Blender scripts with the model-specific native CLI and effort from configs/release/model-harness-contract.json."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    common = _direct_common_parser()

    text_parser = subparsers.add_parser(
        "text",
        parents=[common],
        help="Generate a bpy script from a text scene description.",
    )
    text_input = text_parser.add_mutually_exclusive_group(required=True)
    text_input.add_argument("--prompt", help="Scene description text.")
    text_input.add_argument(
        "--prompt-file", type=Path, help="UTF-8 file containing the scene description."
    )

    image_parser = subparsers.add_parser(
        "image",
        parents=[common],
        help="Generate a bpy script that reconstructs a reference image.",
    )
    image_parser.add_argument(
        "--image", type=Path, required=True, help="Local reference image."
    )
    image_input = image_parser.add_mutually_exclusive_group()
    image_input.add_argument(
        "--prompt", help="Optional extra reconstruction requirements."
    )
    image_input.add_argument(
        "--prompt-file", type=Path, help="UTF-8 file with extra requirements."
    )

    task_parser = subparsers.add_parser(
        "task",
        parents=[_provider_parser()],
        help="Generate a Blender script or UE5 project from a task bundle.",
    )
    task_parser.add_argument(
        "--task",
        required=True,
        dest="task_spec",
        help="Task id such as L1/Text2Code, or a task directory path.",
    )
    task_parser.add_argument(
        "--tasks-root",
        type=Path,
        default=DEFAULT_TASKS_ROOT,
        help=f"Task collection root (default: {DEFAULT_TASKS_ROOT}).",
    )
    task_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Submission directory (default: data/task_runs/<level>__<task>).",
    )
    task_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacing generated files in an existing submission directory.",
    )
    return parser


def _read_prompt(prompt: str | None, prompt_file: Path | None) -> str | None:
    if prompt_file is not None:
        return prompt_file.expanduser().resolve().read_text(encoding="utf-8")
    return prompt


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        benchmark_task = None
        if args.command == "task":
            benchmark_task = load_benchmark_task(args.task_spec, args.tasks_root)
            benchmark_task.validate_materialized_assets()
            output_dir = args.output_dir or default_task_run_dir(benchmark_task)
            output_dir = output_dir.expanduser().resolve()
            output = (
                output_dir / "solution.py"
                if benchmark_task.level in {1, 2}
                else output_dir / "project"
            )
        else:
            output = resolve_output_path(args.output)
            if output.exists() and not args.overwrite:
                raise GeneratorError(
                    f"Output script already exists: {output}; "
                    "pass --overwrite to replace it"
                )
            prompt = _read_prompt(args.prompt, args.prompt_file)

        config = GeneratorConfig.from_env(args.env_file,model=args.model.strip() if args.model is not None else None)
        if args.model is not None:
            model = args.model.strip()
            if not model:
                raise GeneratorError("--model must not be empty")
            config = replace(config, model=model)
        if args.runtime is not None:
            config = replace(config, runtime=args.runtime)
        if args.timeout is not None:
            if args.timeout <= 0:
                raise GeneratorError("--timeout must be greater than zero")
            config = replace(config, timeout=args.timeout)
        if args.max_attempts is not None:
            if args.max_attempts <= 0:
                raise GeneratorError("--max-attempts must be greater than zero")
            config = replace(config, max_attempts=args.max_attempts)
        if args.reasoning_effort is not None:
            config = replace(config, reasoning_effort=args.reasoning_effort)
        generator = BpyScriptGenerator(config)

        print(f"[generator] command: {args.command}", flush=True)
        print(f"[generator] model: {config.model}", flush=True)
        print(f"[generator] runtime: {config.runtime}", flush=True)
        if args.command == "text":
            script = generator.from_text(prompt or "")
            write_script(script, output, overwrite=args.overwrite)
        elif args.command == "image":
            script = generator.from_image(args.image, prompt=prompt)
            write_script(script, output, overwrite=args.overwrite)
        else:
            assert benchmark_task is not None
            print(f"[generator] benchmark task: {benchmark_task.task_id}", flush=True)
            if benchmark_task.level in {1, 2}:
                output = generate_task_submission(
                    generator,
                    benchmark_task,
                    output_dir=output_dir,
                    overwrite=args.overwrite,
                )
            else:
                from .ue5_project import generate_ue5_task_submission

                output = generate_ue5_task_submission(
                    generator,
                    benchmark_task,
                    output_dir=output_dir,
                    overwrite=args.overwrite,
                )
    except (GeneratorError, OSError) as error:
        print(f"[generator] error: {error}", file=sys.stderr)
        return 1

    print(f"[generator] saved: {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
