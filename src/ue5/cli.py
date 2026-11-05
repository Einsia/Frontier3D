"""CLI for UE5 environment validation and project smoke execution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runtime import (
    UE5Config,
    UE5Error,
    build_package_command,
    build_smoke_command,
    inspect_environment,
    prepare_docker_mount,
    run_command,
    validate_project,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and execute UE5 projects.")
    parser.add_argument("--env-file", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Check the configured UE5 runtime.")
    validate = subparsers.add_parser("validate", help="Validate project structure.")
    validate.add_argument("--project", type=Path, required=True)
    for name in ("smoke", "package"):
        child = subparsers.add_parser(name)
        child.add_argument("--project", type=Path, required=True)
        child.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = UE5Config.from_env(args.env_file)
        if args.command == "doctor":
            report = inspect_environment(config)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        project_report = validate_project(args.project)
        if args.command == "validate":
            print(json.dumps(project_report, ensure_ascii=False, indent=2))
            return 0
        environment = inspect_environment(config)
        if not environment["ready"]:
            raise UE5Error("; ".join(environment["errors"]))
        project_file = Path(project_report["project_file"])
        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        if config.mode == "docker":
            prepare_docker_mount(project_file.parent)
            prepare_docker_mount(output_dir)
        command = (
            build_smoke_command(config, project_file, output_dir)
            if args.command == "smoke"
            else build_package_command(config, project_file, output_dir)
        )
        result = run_command(command, config.timeout, project_file.parent)
        (output_dir / f"ue5_{args.command}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        public_result = {
            key: value
            for key, value in result.items()
            if key not in {"stdout", "stderr"}
        }
        print(json.dumps(public_result, indent=2))
        return 0 if result["status"] == "passed" else 1
    except (OSError, UE5Error) as error:
        print(f"[ue5] error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
