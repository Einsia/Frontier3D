"""Command-line launcher for executing generated scripts in Blender.

This module intentionally runs with a normal Python interpreter.  The actual
scene construction happens in :mod:`src.render.blender_runner`, which is loaded
by Blender and therefore has access to ``bpy``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT_DIR = PROJECT_ROOT / "data" / "output_script"
DEFAULT_SCENE_DIR = PROJECT_ROOT / "data" / "output_scene"
BLENDER_RUNNER = Path(__file__).resolve().with_name("blender_runner.py")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute a generated Python script in Blender and save a .blend scene."
    )
    parser.add_argument(
        "--script",
        type=Path,
        help="Generated Blender Python script. If omitted, the input directory must contain exactly one .py file.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_SCRIPT_DIR,
        help=f"Directory containing generated scripts (default: {DEFAULT_SCRIPT_DIR}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SCENE_DIR,
        help=f"Directory for generated .blend files (default: {DEFAULT_SCENE_DIR}).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Exact output .blend path. Overrides --output-dir.",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=None,
        help="Blender executable. Defaults to $BLENDER_BIN or 'blender' on PATH.",
    )
    parser.add_argument(
        "--working-dir",
        type=Path,
        help=(
            "Working directory visible to the generated script "
            "(default: the script directory)."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow an existing output .blend file to be replaced.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="Maximum Blender runtime in seconds (default: 600). Use 0 to disable.",
    )
    return parser


def _resolve_path(path: Path) -> Path:
    """Resolve a path without requiring it to exist yet."""

    return path.expanduser().resolve()


def _select_script(script: Path | None, input_dir: Path) -> Path:
    if script is not None:
        selected = _resolve_path(script)
        if not selected.is_file():
            raise FileNotFoundError(f"Generated script does not exist: {selected}")
        if selected.suffix.lower() != ".py":
            raise ValueError(f"Generated script must have a .py extension: {selected}")
        return selected

    directory = _resolve_path(input_dir)
    if not directory.is_dir():
        raise FileNotFoundError(f"Script directory does not exist: {directory}")
    scripts = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".py"
    )
    if not scripts:
        raise FileNotFoundError(f"No Python scripts found in: {directory}")
    if len(scripts) > 1:
        names = ", ".join(path.name for path in scripts)
        raise ValueError(
            f"Multiple Python scripts found ({names}); pass --script explicitly"
        )
    return scripts[0].resolve()


def _output_path(script: Path, output_dir: Path, output_file: Path | None) -> Path:
    if output_file is not None:
        output = _resolve_path(output_file)
    else:
        output = _resolve_path(output_dir) / f"{script.stem}.blend"
    if output.suffix.lower() != ".blend":
        raise ValueError(f"Output file must have a .blend extension: {output}")
    return output


def _find_blender(blender: Path | None) -> str:
    requested = blender or (
        Path(os.environ["BLENDER_BIN"]) if os.environ.get("BLENDER_BIN") else None
    )
    if requested is not None:
        expanded = requested.expanduser()
        requested_text = str(expanded)
        resolved = (
            str(expanded.resolve())
            if expanded.is_file()
            else shutil.which(requested_text)
        )
        if resolved is None or not Path(resolved).is_file():
            raise FileNotFoundError(f"Blender executable not found: {requested_text}")
        return resolved

    resolved = shutil.which("blender")
    if resolved is None:
        raise FileNotFoundError(
            "Blender executable not found. Install Blender or pass --blender /path/to/blender."
        )
    return resolved


def build_command(
    blender: str,
    script: Path,
    output: Path,
    overwrite: bool,
    working_directory: Path | None = None,
) -> list[str]:
    """Build the Blender command separately so it can be tested without Blender."""

    command = [
        blender,
        "--background",
        "--factory-startup",
        "-noaudio",
        "--python-exit-code",
        "1",
        "--python",
        str(BLENDER_RUNNER),
        "--",
        "--script",
        str(script),
        "--output",
        str(output),
    ]
    if working_directory is not None:
        command.extend(("--working-dir", str(working_directory)))
    if overwrite:
        command.append("--overwrite")
    return command


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.timeout < 0:
        parser.error("--timeout must be non-negative")

    try:
        script = _select_script(args.script, args.input_dir)
        output = _output_path(script, args.output_dir, args.output_file)
        working_directory = _resolve_path(args.working_dir or script.parent)
        if not working_directory.is_dir():
            raise FileNotFoundError(
                f"Script working directory does not exist: {working_directory}"
            )
        if output.exists() and not args.overwrite:
            raise FileExistsError(
                f"Output already exists: {output}; pass --overwrite to replace it"
            )
        blender = _find_blender(args.blender)
    except (FileExistsError, FileNotFoundError, ValueError) as error:
        parser.error(str(error))

    output.parent.mkdir(parents=True, exist_ok=True)
    command = build_command(
        blender,
        script,
        output,
        args.overwrite,
        working_directory=working_directory,
    )
    print(f"[render] script: {script}", flush=True)
    print(f"[render] output: {output}", flush=True)
    print(f"[render] working directory: {working_directory}", flush=True)

    blender_environment = os.environ.copy()
    blender_cache = PROJECT_ROOT / ".cache" / "blender"
    blender_cache.mkdir(parents=True, exist_ok=True)
    blender_environment["XDG_CACHE_HOME"] = str(blender_cache)

    try:
        completed = subprocess.run(
            command,
            cwd=working_directory,
            check=False,
            env=blender_environment,
            timeout=args.timeout or None,
        )
    except subprocess.TimeoutExpired:
        print(
            f"[render] Blender timed out after {args.timeout:g} seconds",
            file=sys.stderr,
        )
        return 124
    except OSError as error:
        print(f"[render] Failed to start Blender: {error}", file=sys.stderr)
        return 1

    if completed.returncode != 0:
        if completed.returncode < 0:
            signal_number = -completed.returncode
            print(
                f"[render] Blender was terminated by signal {signal_number}",
                file=sys.stderr,
            )
            return 128 + signal_number
        print(
            f"[render] Blender exited with code {completed.returncode}", file=sys.stderr
        )
        return completed.returncode
    if not output.is_file():
        print(
            f"[render] Blender exited successfully but did not create: {output}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
