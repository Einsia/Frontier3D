"""Render a saved primary camera and verify its scene and image receipts."""
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from benchmark.resources import ROOT, blender_path
from src.agent_judge.protocol import contract_hash, digest, read_json, write_json
from tools.native_scene import bound

BLENDER = blender_path()
WORKER = ROOT / 'src/evaluator/continuous_image_saved_blender.py'

class Evidence:
    """Hash each distinct file once per report invocation."""
    def __init__(self): self.checked = set()

    def check(self, pointer):
        identity = (pointer['path'], pointer['sha256'])
        if identity not in self.checked:
            bound(*identity); self.checked.add(identity)
        return pointer

    def tree(self, value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value: self.check(value)
            else:
                for item in value.values(): self.tree(item)
        elif isinstance(value, list):
            for item in value: self.tree(item)

def _archive_saved_render(output):
    archive = output/('native-crash-'+str(time.time_ns()))
    archive.mkdir(mode=0o777); archive.chmod(0o777)
    for name in ('worker.log', 'execution.json', 'result.json',
                 'primary_beauty.png', 'primary_geometry.png'):
        path = output/name
        if path.exists():
            path.rename(archive/name)
    return archive

def _run_saved_render(source, output, *, timeout=900):
    """Retry a native crash once in a fresh process within one time budget.

    A successful diagnostic of the same retained bytes demonstrates that a
    native crash alone cannot establish a candidate defect. Preserve each
    crash and partial output; never treat it as a zero-valued measurement.
    """
    from tools.native_render_budget import budget
    timeout, threads = budget(source['sha256'], timeout, 2)
    start = time.monotonic()
    attempts = []
    if (output/'worker.log').exists() or (output/'execution.json').exists():
        _archive_saved_render(output)
    for attempt in range(2):
        bound(source['path'], source['sha256'])
        if attempt:
            attempts[-1]['archive'] = str(_archive_saved_render(output))
        remaining = timeout-(time.monotonic()-start)
        if remaining <= 0:
            raise subprocess.TimeoutExpired('Saved image render shared deadline', timeout)
        began = time.monotonic()
        try:
            with (output/'worker.log').open('w') as log:
                process = subprocess.run([str(BLENDER), '-b', '--factory-startup', '--disable-autoexec',
                    '--threads', str(threads), '--python-exit-code', '1', '--python', str(WORKER), '--',
                    str(output/'request.json')], stdout=log, stderr=subprocess.STDOUT, timeout=remaining,
                    env={**os.environ, 'OMP_NUM_THREADS': str(threads), 'OPENBLAS_NUM_THREADS': '2'})
        except subprocess.TimeoutExpired:
            attempts.append({'seconds': time.monotonic()-began, 'returncode': None, 'status': 'timeout'})
            write_json(output/'execution.json', {'seconds': time.monotonic()-start,
                'returncode': None, 'status': 'timeout', 'attempts': attempts,
                'candidate_code_executed': False, 'model_calls': 0})
            raise
        attempts.append({'seconds': time.monotonic()-began, 'returncode': process.returncode})
        write_json(output/'execution.json', {'seconds': time.monotonic()-start,
            'returncode': process.returncode, 'attempts': attempts,
            'candidate_code_executed': False, 'model_calls': 0})
        bound(source['path'], source['sha256'])
        if process.returncode == 0:
            return
        if process.returncode not in {-signal.SIGSEGV, -signal.SIGABRT} or attempt:
            raise ValueError('Saved image render failed: '+str(output/'worker.log'))

def saved_render(source, folder, frame, resolution):
    request = {'scene': source, 'frame': frame, 'resolution': resolution}
    revision = contract_hash(json.dumps({'request': request, 'worker': digest(WORKER),
        'renderer': digest(ROOT/'src/evaluator/l1_image_blender.py')}, sort_keys=True))[:20]
    output = folder/revision
    created = [p for p in (output, *output.parents) if not p.exists()]
    output.mkdir(parents=True, exist_ok=True)
    for p in created: p.chmod(0o777)
    request.update(output=str(output), request_path=str(output/'request.json'))
    with (output/'worker.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = output/'result.json'
        if not path.exists():
            write_json(output/'request.json', request)
            _run_saved_render(source, output)
        execution = output/'execution.json'
        if execution.exists() and read_json(execution).get('returncode') != 0:
            raise ValueError('Saved render has no successful execution receipt')
        result = read_json(path)
        if (read_json(output/'request.json') != request or result['request_sha256'] != digest(output/'request.json')
                or result['worker_sha256'] != digest(WORKER)
                or result['renderer_sha256'] != digest(ROOT/'src/evaluator/l1_image_blender.py')
                or result['scene'] != source or not result['source_unchanged']):
            raise ValueError('Saved render provenance differs')
        Evidence().tree(result); return result, bound(path)
