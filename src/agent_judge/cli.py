"""python -m src.agent_judge run|score"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from jsonschema import ValidationError

from .generated import verified_evidence
from .packet import prepare
from .protocol import digest, read_json, score, write_json
from .runtime import run_codex


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="3DBench Agent Judge: issue JSON -> fixed S_vlm"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument(
        "--task", type=Path, required=True, help="Task directory with instruction.md"
    )
    run.add_argument(
        "--submission", type=Path, required=True, help="Output directory or its parent"
    )
    run.add_argument(
        "--output",
        type=Path,
        required=True,
        help="NEW run directory; never overwritten",
    )
    run.add_argument("--spec", type=Path, help="Defaults to bundled per-task JudgeSpec")
    run.add_argument(
        "--reference", type=Path, help="Override benchmark reference directory"
    )
    run.add_argument(
        "--mode", choices=["interactive", "visual", "asset"], default="interactive"
    )
    run.add_argument(
        "--blender",
        help="Blender executable (interactive tools; fixed prerender in other modes)",
    )
    run.add_argument("--model", default="gpt-6-luna")
    run.add_argument(
        "--effort", choices=["low", "medium", "high", "xhigh"], default="medium"
    )
    run.add_argument("--timeout", type=float, default=900)
    run.add_argument("--render-timeout", type=float, default=90)
    run.add_argument("--tool-budget", type=int, default=12)
    run.add_argument("--attempts", type=int, default=2)
    run.add_argument("--codex", default=shutil.which("codex") or "codex")
    run.add_argument(
        "--codex-home",
        type=Path,
        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
    )
    run.add_argument("--runtime", choices=["local", "docker"], default="local")
    run.add_argument("--docker-image", default="3dbench-agent-judge:local")
    run.add_argument(
        "--prepare-only", action="store_true", help="Freeze packet without an API call"
    )
    replay = commands.add_parser(
        "score", help="Validate and rescore offline without invoking Codex"
    )
    replay.add_argument("--packet", type=Path, required=True)
    replay.add_argument("--response", type=Path, required=True)
    replay.add_argument("--output", type=Path, required=True)
    replay.add_argument(
        "--generated",
        type=Path,
        help="Accepted attempt's generated/ directory for interactive evidence",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "score":
            manifest = read_json(args.packet / "manifest.json")
            for path, sha in manifest["sha256"].items():
                resolved = (args.packet / path).resolve()
                if (
                    not resolved.is_relative_to(args.packet.resolve())
                    or digest(resolved) != sha
                ):
                    raise ValueError("Evidence packet changed")
            report = score(
                read_json(args.response),
                read_json(args.packet / "judge_spec.json"),
                verified_evidence(manifest, args.generated),
            )
            write_json(args.output, report)
            print(f"{report['status']}: S_vlm={report['S_vlm']} -> {args.output}")
            return 0
        if args.timeout <= 0 or args.attempts < 1:
            raise ValueError("Timeout and attempts must be positive")
        if not 1 <= args.tool_budget <= 32 or args.render_timeout <= 0:
            raise ValueError(
                "Tool budget must be 1..32 and render timeout must be positive"
            )
        if args.mode == "interactive":
            args.blender = args.blender or (
                "blender" if args.runtime == "docker" else shutil.which("blender")
            )
            if not args.blender:
                raise ValueError(
                    "Interactive mode needs --blender PATH (or Blender on PATH); use --mode visual for images only"
                )
        task = args.task.resolve()
        spec_path = (
            args.spec
            or Path(__file__).parents[2]
            / "configs"
            / "agent_judge"
            / f"{task.name}.json"
        )
        spec = read_json(spec_path)
        selected_protocol = spec['protocol']
        output = args.output.resolve()
        if output.exists():
            raise ValueError(
                "Output already exists; use a fresh path (offline score is replayable)"
            )
        submission = args.submission.resolve()
        if output.is_relative_to(submission) or submission.is_relative_to(output):
            raise ValueError("Judge output must be separate from candidate inputs")
        output.mkdir(parents=True)
        write_json(
            output / "run.json",
            {
                "protocol": selected_protocol,
                "status": "preparing",
                "model": args.model,
                "runtime": args.runtime,
            },
        )
        try:
            manifest = prepare(
                task,
                submission,
                spec,
                output / "packet",
                mode=args.mode,
                blender=args.blender,
                timeout=args.timeout,
                reference=args.reference.resolve() if args.reference else None,
                tool_budget=args.tool_budget,
            )
            if args.prepare_only:
                write_json(
                    output / "run.json", {"protocol": selected_protocol, "status": "prepared"}
                )
                print(
                    f"Prepared {len(manifest['images'])} views -> {output / 'packet'}"
                )
                return 0
            failures = []
            for attempt in range(1, args.attempts + 1):
                directory = output / f"attempt-{attempt}"
                write_json(
                    output / "run.json",
                    {
                        "protocol": selected_protocol,
                        "status": "running",
                        "attempt": attempt,
                        "model": args.model,
                        "effort": args.effort,
                        "runtime": args.runtime,
                        "previous_failures": failures,
                    },
                )
                execution = run_codex(
                    output / "packet",
                    directory,
                    model=args.model,
                    effort=args.effort,
                    codex=args.codex,
                    codex_home=args.codex_home,
                    timeout=args.timeout,
                    runtime=args.runtime,
                    docker_image=args.docker_image,
                    blender=args.blender,
                    render_timeout=args.render_timeout,
                )
                if (
                    execution["timed_out"]
                    or execution["returncode"] != 0
                    or execution["modified_inputs"]
                ):
                    failures.append(
                        {
                            "attempt": attempt,
                            "reason": "timeout, nonzero exit or modified evidence",
                            "execution": execution,
                        }
                    )
                    continue
                try:
                    response = read_json(directory / "response.json")
                    evidence = verified_evidence(
                        manifest,
                        directory / "generated" if args.mode == "interactive" else None,
                    )
                    report = score(response, spec, evidence)
                except (OSError, ValueError, ValidationError):
                    failures.append(
                        {
                            "attempt": attempt,
                            "reason": "Missing/invalid issue JSON; see attempt artifacts",
                        }
                    )
                    continue
                write_json(output / "issues.json", response)
                write_json(output / "score.json", report)
                write_json(
                    output / "run.json",
                    {
                        "protocol": selected_protocol,
                        "status": report["status"],
                        "model": args.model,
                        "effort": args.effort,
                        "runtime": args.runtime,
                        "attempt": attempt,
                        "execution": execution,
                        "previous_failures": failures,
                        "packet_sha256": digest(output / "packet" / "manifest.json"),
                        "response_sha256": digest(output / "issues.json"),
                        "spec_sha256": digest(output / "packet" / "judge_spec.json"),
                    },
                )
                print(
                    f"{report['status']}: S_vlm={report['S_vlm']}, coverage={report['coverage']:.3f} -> {output}"
                )
                return 0
            write_json(
                output / "run.json",
                {"protocol": selected_protocol, "status": "failed", "failures": failures},
            )
            print(f"Judge failed; no score assigned. Inspect {output / 'run.json'}")
            return 1
        except (
            OSError,
            ValueError,
            RuntimeError,
            ValidationError,
            subprocess.SubprocessError,
        ) as error:
            write_json(
                output / "run.json",
                {
                    "protocol": selected_protocol,
                    "status": "failed",
                    "error_type": type(error).__name__,
                },
            )
            raise
    except (
        OSError,
        ValueError,
        RuntimeError,
        ValidationError,
        subprocess.SubprocessError,
    ) as error:
        # Do not dump subprocess output or structured API payloads into terminal logs.
        print(
            f"Agent Judge error: {type(error).__name__}: {str(error).splitlines()[0][:220]}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
