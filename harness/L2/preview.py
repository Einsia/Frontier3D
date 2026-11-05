"""Model-visible draft execution using the same isolated Blender as final runs."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from harness.common.attempt_log import write_json
from .audit import regular_file
from .executor import run_process, sandbox_command
from .safe_io import read_bytes, publish


def execution_error_summary(directory, limit=4096):
    """Bounded diagnostic from controller-owned logs, not candidate artifacts."""
    for name in ('stderr.log', 'stdout.log'):
        path = directory/name
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell()-limit))
            text = stream.read(limit).decode('utf-8', errors='replace').strip()
        if text:
            return ''.join(c for c in text if c in '\n\t' or c.isprintable())
    return 'Blender exited unsuccessfully; no diagnostic output was available.'


def preview(workspace, blender, inputs, timeout, threads=8, *, request_dir=None, cancel_event=None,
            policy=None, frozen_inputs=None):
    workspace = workspace.resolve()
    code = read_bytes(workspace, "solution.py")
    run = request_dir or workspace / ".preview" / str(time.time_ns())
    run.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="l2-preview-") as tmp:
        stage = Path(tmp)
        (stage / "solution.py").write_bytes(code)
        for name in inputs:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(regular_file(frozen_inputs or workspace, name), target)
        command = sandbox_command(blender, stage, Path(__file__).with_name("execute_worker.py"), [], threads=threads)
        result = run_process(command, cwd=stage, logs=run, timeout=timeout, cancel_event=cancel_event)
        data = result.to_dict()
        data['execution_status'] = result.status
        data['execution_passed'] = result.status == 'success'
        if result.status == 'process_error':
            data.update(status='candidate_runtime_error', failure_stage='candidate_execution',
                        error_summary=execution_error_summary(run))
        if policy is not None and data['execution_passed']:
            from .preflight import check_outputs
            data['preflight'] = check_outputs(stage, blender, policy, run/'preflight',
                max(0, timeout-(time.monotonic()-started)), cancel_event=cancel_event)
            if not data['preflight']['passed']:
                data['status'] = 'timeout' if data['preflight'].get('timed_out') else 'invalid_submission'
                data['error_code'] = 'PUBLIC_PREFLIGHT_TIMEOUT' if data['status'] == 'timeout' else 'PUBLIC_PREFLIGHT_FAILED'
        for name in ('scene_diagnostics.json', 'scene_diagnostics.png', 'road_diagnostics.png', 'road_grid.npz'):
            path = run/'preflight'/name
            if path.is_file():
                publish(workspace, name, path.read_bytes())
        for name in ("scene.blend", "main.png", "alternate.png"):
            if (stage / name).exists():
                source = regular_file(stage, name)
                publish(workspace, name, source.read_bytes())
    data['elapsed_seconds'] = time.monotonic()-started
    from harness.common.attempt_log import sha256_bytes
    data['source_code_sha256'] = sha256_bytes(code)
    write_json(run / "result.json", data)
    if request_dir is None:
        for name in ("stdout.log", "stderr.log"):
            print((run / name).read_text(errors="replace")[-12000:])
        print(json.dumps(data))
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--threads", type=int, default=8)
    args = parser.parse_args(argv)
    result = preview(args.workspace, args.blender, json.loads(args.inputs), args.timeout, args.threads)
    return 0 if result['status'] == 'success' else 1


if __name__ == "__main__":
    raise SystemExit(main())
