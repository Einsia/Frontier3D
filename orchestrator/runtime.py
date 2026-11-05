"""Container/process lifecycle and retry policy, external to every task pack."""
from __future__ import annotations

import math
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path

from .process_io import MAX_PIPE_BYTES, communicate_bounded

from .tasks import write_json


def seconds(value):
    if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
        raise ValueError('Timeout must be a positive finite number')
    return float(value)


def run_process(command, *, cwd, directory, deadline, timeout, env=None, container=None,
                input_bytes=None, docker_binary='docker', max_pipe_bytes=MAX_PIPE_BYTES):
    seconds(timeout)
    start = time.monotonic()
    end = min(deadline, start+timeout)
    directory.mkdir(parents=True, exist_ok=False)
    record = {'command': command, 'status': 'not_started', 'pid': None,
              'deadline_monotonic': end, 'started_monotonic': start, 'return_code': None,
              'container': container, 'leader_reaped': False}
    record['max_pipe_bytes'] = max_pipe_bytes
    process = None
    interrupted = None
    stdout = stderr = ''
    environment = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT'}}
    environment.update(env or {})
    try:
        if start >= end:
            record['status'] = 'budget_exhausted'
        else:
            process = subprocess.Popen(command, cwd=cwd, env=environment,
                                       stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            record['pid'] = process.pid
            stdout, stderr = communicate_bounded(process, timeout=max(0, end-time.monotonic()),
                                                 input_bytes=input_bytes, max_input_bytes=16*1024*1024,
                                                 max_pipe_bytes=max_pipe_bytes)
            record['status'] = 'success' if process.returncode == 0 else 'process_error'
            if time.monotonic() >= end:
                record['status'] = 'timeout'
    except subprocess.TimeoutExpired as error:
        record['status'] = 'timeout'
        stdout = (error.output or b'').decode(errors='replace') if isinstance(error.output, bytes) else error.output or ''
        stderr = (error.stderr or b'').decode(errors='replace') if isinstance(error.stderr, bytes) else error.stderr or ''
    except (KeyboardInterrupt, SystemExit) as error:
        record['status'] = 'interrupted'
        interrupted = error
    except (OSError, ValueError, RuntimeError) as error:
        record.update(status='infrastructure_error', error_type=type(error).__name__, error=str(error)[:4096])
        # Bounded collectors attach the captured prefix to limit/encoding
        # errors. Retain it for diagnosis instead of writing empty logs.
        stdout = getattr(error, 'stdout', stdout)
        stderr = getattr(error, 'stderr', stderr)
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
                record['leader_reaped'] = True
            except subprocess.TimeoutExpired:
                record['status'] = 'cleanup_failed'
            record['return_code'] = process.returncode
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        if container is not None:
            try:
                removal = subprocess.run([docker_binary, 'rm', '-f', container], capture_output=True, timeout=5, check=False)
                # --rm can have removed the container already; inspect verifies absence.
                probe = subprocess.run([docker_binary, 'container', 'inspect', container], capture_output=True, timeout=5, check=False)
                absent = probe.returncode != 0 and b'No such' in probe.stderr
                record['container_removed'] = absent
                record['container_remove_return_code'] = removal.returncode
                if not absent:
                    record['status'] = 'cleanup_failed'
            except (OSError, subprocess.TimeoutExpired):
                record.update(container_removed=False, status='cleanup_failed')
        record['elapsed_seconds'] = time.monotonic()-start
        (directory / 'stdout.log').write_text(stdout)
        (directory / 'stderr.log').write_text(stderr)
        write_json(directory / 'process.json', record)
    if interrupted is not None:
        interrupted.orchestrator_execution = record
        raise interrupted
    return record


def blender_command(workspace: Path, blender: Path, *, runtime, image, seed, memory="4g", level=1):
    cpus = min(8 if level == 2 else 2, len(os.sched_getaffinity(0)))
    options = ['--background', '--factory-startup', '--disable-autoexec', '--threads', str(cpus),
               '--python-exit-code', '1', '--python', 'output/solution.py', '--',
               '--input-dir', str(workspace / 'input'), '--output-dir', str(workspace / 'output')]
    if runtime == 'local':
        return [str(blender), *options], None
    if runtime != 'docker':
        raise ValueError('Unknown candidate runtime')
    name = f'3dbench-l{level}-'+uuid.uuid4().hex
    # A CPU quota alone leaves all host CPUs visible to native thread pools.
    # Restrict affinity as well, so Blender startup fits the process limit.
    # Rotate the window across the host: a fixed [:cpus] slice pins every
    # concurrent container onto the same first cores, starving them while the
    # rest of the machine idles.
    allowed = sorted(os.sched_getaffinity(0))
    offset = (os.getpid() * cpus) % len(allowed)
    window = [allowed[(offset + index) % len(allowed)] for index in range(cpus)]
    cpu_set = ','.join(str(cpu) for cpu in sorted(set(window)))
    # No task root, solution/, evaluator, run archive or host credentials mount.
    options[-3], options[-1] = '/workspace/input', '/workspace/output'
    command = ['docker', 'run', '--rm', '--name', name, '--network', 'none', '--read-only',
               '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--pids-limit', '512', '--memory', memory, '--cpus', str(cpus), '--cpuset-cpus', cpu_set,
               '--user', f'{os.getuid()}:{os.getgid()}', '--tmpfs', '/tmp:rw,size=1g,mode=1777',
               '--env', 'HOME=/tmp', '--env', f'PYTHONHASHSEED={seed}', '--env', f'THREEDBENCH_SEED={seed}',
               '--env', f'OMP_NUM_THREADS={cpus}', '--env', 'OPENBLAS_NUM_THREADS=2',
               '--mount', f'type=bind,src={workspace / "input"},dst=/workspace/input,readonly',
               '--mount', f'type=bind,src={workspace / "output"},dst=/workspace/output',
               '--mount', f'type=bind,src={blender.parent},dst=/opt/blender,readonly',
               '--workdir', '/workspace', image, *options]
    return command, name


def retry(operation, *, attempts, deadline, backoff=0):
    if type(attempts) is not int or not 1 <= attempts <= 10 or not math.isfinite(backoff) or backoff < 0:
        raise ValueError('Invalid retry policy')
    history = []
    for index in range(attempts):
        if time.monotonic() >= deadline:
            break
        row = operation(index, deadline)
        history.append(row)
        if row['status'] == 'success' or row.get('retryable') is False:
            break
        if index+1 < attempts and backoff:
            time.sleep(min(backoff, max(0, deadline-time.monotonic())))
    return history
