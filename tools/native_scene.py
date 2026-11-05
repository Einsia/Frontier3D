"""Hash-bound native scene inspection used by mechanism detail scoring."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from benchmark.resources import ROOT, blender_path
from src.agent_judge.protocol import contract_hash, digest, read_json, write_json

BLENDER = blender_path()
WORKER = ROOT / 'src/evaluator/continuous_native_blender.py'
KERNEL = ROOT / 'src/evaluator/continuous_surface.py'

def bound(path, expected=None):
    path = Path(path).resolve(strict=True)
    if not (path.is_relative_to(ROOT / 'data') or path.is_relative_to(Path(os.environ['THREEDBENCH_RUN_ROOT']))): raise ValueError('Native source outside declared inputs and run output')
    sha = digest(path)
    if expected and sha != expected: raise ValueError('Native source changed')
    return {'path': str(path), 'sha256': sha}

def worker(request, directory, timeout=900):
    metadata = {'worker_sha256': digest(WORKER), 'surface_kernel_sha256': digest(KERNEL),
        'inspector_properties_sha256': digest(ROOT / 'src/evaluator/l2_case_blender.py')}
    revision = contract_hash(json.dumps({'request': request, 'implementation': metadata}, sort_keys=True))[:20]
    directory = Path(directory).resolve() / revision
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _worker_locked(request, directory, timeout, metadata)

def _worker_locked(request, directory, timeout, metadata):
    request = {**request, 'output': str(directory)}
    record = {'request': request, 'implementation': metadata}
    pin = directory / 'contract.json'; result_path = directory / 'result.json'
    if pin.exists() and read_json(pin) != record: raise ValueError('Native cache contract changed; use a new revision')
    if result_path.is_file():
        result = read_json(result_path)
        if result['request_sha256'] != digest(directory / 'request.json'):
            raise ValueError('Native cache request hash changed')
        if any(result[k] != metadata[k] for k in ('worker_sha256', 'surface_kernel_sha256')):
            raise ValueError('Native cache implementation changed')
        for snapshot in result['result'].get('snapshots', []):
            for item in snapshot['objects']:
                if item.get('geometry'): bound(**{'path': item['geometry']['path'], 'expected': item['geometry']['sha256']})
        return result['result']
    write_json(pin, record); write_json(directory / 'request.json', request)
    start = time.monotonic()
    with (directory / 'worker.log').open('w') as stream:
        process = subprocess.run([str(BLENDER), '-b', '--factory-startup', '--disable-autoexec', '--threads', '2',
            '--python-exit-code', '1', '--python', str(WORKER), '--', str(directory / 'request.json')],
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
            env={**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'})
    write_json(directory / 'execution.json', {'seconds': time.monotonic()-start, 'returncode': process.returncode,
        'candidate_code_executed': False, 'model_calls': 0, 'blender': str(BLENDER)})
    if process.returncode: raise ValueError('Native worker failed: ' + str(directory / 'worker.log'))
    return read_json(result_path)['result']

def inspect(scene, output, frames=(1,)):
    bound(scene['path'], scene['sha256'])
    result = worker({'operation': 'inspect', 'scene': scene, 'frames': list(frames)}, output)
    if result['scene'] != scene or not result['source_unchanged']:
        raise ValueError('Invalid scene extraction provenance')
    return result
