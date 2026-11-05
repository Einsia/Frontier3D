#!/usr/bin/env python3
"""Public development helpers. No reference data, hidden plans, or scoring."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys


def project_file(value: str) -> Path:
    path = Path(value).resolve()
    if path.is_dir():
        matches = list(path.glob("*.uproject"))
        if len(matches) != 1:
            raise ValueError("Specify a directory with exactly one .uproject")
        path = matches[0]
    if not path.is_file() or path.suffix != ".uproject":
        raise ValueError("Project file is missing")
    json.loads(path.read_text())
    return path


def execute(command: list[str], log: Path, timeout: int | None) -> None:
    print(f"Log: {log}", flush=True)
    process = None
    finished = False

    def interrupted(signum, _frame):
        # Native harness timeouts terminate this wrapper, not its new session.
        # Unwind through finally so the development process group is reaped.
        raise SystemExit(128 + signum)

    previous = {sig: signal.getsignal(sig)
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    for sig, handler in previous.items():
        # Preserve nohup/background callers that deliberately ignore a signal.
        if handler != signal.SIG_IGN:
            signal.signal(sig, interrupted)
    try:
        with log.open("w") as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"Command timed out after {timeout}s; see {log}")
            finished = True
    finally:
        try:
            if process is not None and not finished:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    if code:
        print("\n".join(log.read_text(errors="replace").splitlines()[-60:]), file=sys.stderr)
        raise RuntimeError(f"Command exited {code}; see {log}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install-interface", "build", "preview"])
    parser.add_argument("project")
    parser.add_argument("--output", help="New directory for logs and preview evidence")
    parser.add_argument("--timeout", type=int, default=None,
                        help="Explicit wall-clock limit in seconds; build defaults to 1800, preview has no default limit")
    parser.add_argument("--jobs", type=int, default=16)
    parser.add_argument("--editor-target")
    parser.add_argument("--blueprints", action="store_true", help="Also compile Blueprints; use when changing Blueprint assets")
    parser.add_argument("--plan", help="Your own observer action plan; never a scoring plan")
    parser.add_argument("--position", nargs=3, type=float)
    parser.add_argument("--target", nargs=3, type=float)
    parser.add_argument("--width",type=int,default=1280)
    parser.add_argument("--height",type=int,default=720)
    args = parser.parse_args()
    project = project_file(args.project)
    if args.command == "install-interface":
        source = Path(os.environ.get("L3_PUBLIC_TOOLS", "/opt/l3-public")) / "BenchRuntime"
        destination = project.parent / "Plugins/BenchRuntime"
        if destination.exists():
            raise ValueError("BenchRuntime already exists; inspect it before replacing it")
        shutil.copytree(source, destination)
        descriptor = json.loads(project.read_text())
        plugins = descriptor.setdefault("Plugins", [])
        plugins[:] = [p for p in plugins if p.get("Name") != "BenchRuntime"]
        plugins.append({"Name": "BenchRuntime", "Enabled": True})
        project.write_text(json.dumps(descriptor, indent=2) + "\n")
        print(destination)
        return
    if not args.output or (args.timeout is not None and args.timeout < 1) or args.jobs < 1:
        raise ValueError("Specify --output and positive --timeout/--jobs")
    # Slow shared GPUs must not truncate a progressing public development plan.
    # Explicit per-call limits remain authoritative; builds keep their old default.
    timeout = args.timeout if args.timeout is not None else (1800 if args.command == "build" else None)
    engine = Path(os.environ["UE5_ROOT"])
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp/ue-runtime"))
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    common = ["-unattended", "-nosplash", "-nosound", "-nop4", "-stdout", "-DDC=NoZenLocalFallback",
              "-FullStdOutLogOutput", f"-corelimit={args.jobs}"]
    if args.command == "build":
        target = args.editor_target
        if not target:
            targets = list((project.parent / "Source").glob("*Editor.Target.cs"))
            if len(targets) != 1:
                raise ValueError("Specify --editor-target when there is not exactly one Editor.Target.cs")
            target = targets[0].name.removesuffix(".Target.cs")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target):
            raise ValueError("Invalid editor target")
        execute([str(engine / "Engine/Build/BatchFiles/Linux/Build.sh"), target,
                 "Linux", "Development", str(project), "-NoHotReload", "-WaitMutex",
                 "-NoUBA", "-UsePrecompiled", f"-MaxParallelActions={args.jobs}"],
                output / "build.log", timeout)
        if args.blueprints:
            execute([str(engine / "Engine/Binaries/Linux/UnrealEditor-Cmd"), str(project),
                     "-run=CompileAllBlueprints", "-NullRHI", *common],
                    output / "blueprints.log", timeout)
        print("C++ build completed" + ("; Blueprint compilation completed" if args.blueprints else "; use --blueprints when editing Blueprint assets"))
        return
    if args.plan:
        plan = json.loads(Path(args.plan).read_text())
        if not isinstance(plan.get("steps"), list):
            raise ValueError("A plan needs a steps array")
    else:
        if args.position is None or args.target is None:
            raise ValueError("Preview requires --position and --target, or --plan")
        plan = {"version": 1, "kind": "development_preview", "steps": [
            {"op": "camera", "name": "camera", "position_cm": args.position,
             "target_cm": args.target},
            {"op": "wait", "name": "settle", "seconds": 2},
            {"op": "capture", "name": "preview"},
        ]}
    plan_path = output / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
    width,height=plan.get('render_size',[args.width,args.height])
    if any(type(v) is not int or not 64<=v<=4096 for v in [width,height]):
        raise ValueError('Render dimensions must be integers in 64..4096')
    execute([str(engine / "Engine/Binaries/Linux/UnrealEditor"), str(project),
             "-game", "-RenderOffscreen", "-vulkan", "-graphicsadapter=0",
             f"-ResX={width}", f"-ResY={height}", "-Windowed", "-ForceRes", "-UseFixedTimeStep", "-FPS=60",
             f"-BenchPlan={plan_path}",
             f"-BenchOutput={output}", *common], output / "editor.log", timeout)
    completed = output / "completed.json"
    if not completed.exists() or not json.loads(completed.read_text()).get("completed"):
        raise RuntimeError("Editor exited without completing the preview plan")
    for step in plan["steps"]:
        if step.get("op") == "capture":
            png = output / (step["name"] + ".png")
            if not png.is_file() or png.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
                raise RuntimeError(f"Screenshot missing or invalid: {png}")
            print(png)
    print("Development preview completed; this is not an evaluation score")


if __name__ == "__main__":
    main()
