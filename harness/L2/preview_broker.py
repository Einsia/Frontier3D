"""Serve only fixed draft-render requests; never execute arbitrary client commands."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time
import tempfile

from harness.common.attempt_log import write_json
from .preview import preview
from .safe_io import read_bytes, publish


def serve(workspace, blender, inputs, timeout, threads, stop, *, policy=None, frozen_inputs=None, deadline=None, observations=None, trusted_root=None):
    processed = set()
    while not stop.is_set():
        for request in workspace.glob(".preview/*/request.json"):
            if request in processed:
                continue
            # Draft output is untrusted; never follow client symlinks outside the workspace.
            if any(p.is_symlink() for p in (workspace / '.preview', request.parent, request)):
                continue
            if not request.resolve().is_relative_to(workspace.resolve()):
                continue
            processed.add(request)
            directory = request.parent
            try:
                if json.loads(read_bytes(workspace, request.relative_to(workspace).as_posix(), max_bytes=1024)) != {"operation": "render_solution"}:
                    raise ValueError("Unsupported preview operation")
                for name in ('stdout.log', 'stderr.log', 'result.json'):
                    if (directory / name).is_symlink():
                        raise ValueError("Unsafe preview log path")
                limit = min(timeout, max(0, deadline-time.monotonic())) if deadline else timeout
                destination = Path(trusted_root)/str(len(processed))
                destination.mkdir(parents=True, exist_ok=True)
                result = preview(workspace, blender, inputs, limit, threads, request_dir=destination,
                                 cancel_event=stop, policy=policy, frozen_inputs=frozen_inputs)
                if observations is not None:
                    observations.append(result)
                for name in ('stdout.log', 'stderr.log', 'result.json'):
                    if (destination/name).is_file():
                        publish(workspace, (directory/name).relative_to(workspace).as_posix(), (destination/name).read_bytes())
            except (OSError, ValueError, RuntimeError) as error:
                try:
                    publish(workspace, (directory/'result.json').relative_to(workspace).as_posix(),
                            json.dumps({'status': 'unavailable', 'error': str(error)}).encode())
                except (OSError, ValueError):
                    pass  # A removed/replaced client directory is not a host write target.
        stop.wait(.25)


@contextmanager
def preview_broker(workspace, blender, inputs, timeout, threads=8, *, policy=None, frozen_inputs=None, deadline=None):
    stop = threading.Event()
    observations = []
    trusted = tempfile.TemporaryDirectory(prefix='l2-preview-broker-')
    thread = threading.Thread(target=serve, args=(workspace, blender, inputs, timeout, threads, stop),
        kwargs=dict(policy=policy, frozen_inputs=frozen_inputs, deadline=deadline, observations=observations, trusted_root=trusted.name), daemon=True)
    thread.start()
    try:
        yield observations
    finally:
        stop.set()
        thread.join(timeout=10)
        trusted.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    parser.add_argument('--timeout', type=float, default=1800)
    args = parser.parse_args()
    stop = threading.Event()
    def monitor():
        while not stop.wait(.5):
            try:
                os.kill(args.parent_pid, 0)
            except ProcessLookupError:
                stop.set()
    threading.Thread(target=monitor, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix='l2-preview-broker-') as trusted:
        serve(args.workspace.resolve(), args.blender.resolve(), json.loads(args.inputs), args.timeout, 8, stop, trusted_root=trusted)


if __name__ == '__main__':
    main()
