"""Budgeted native-image/core GLB snapshots; no candidate execution or retries."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from src.evaluator.l1_budget import DeadlineBudget
from src.evaluator.l1_failures import InspectionFailure

PROTOCOL = 'l1-image-dependency-snapshot-v1'
WORKER = Path(__file__).with_name('l1_resource_worker.py')
MAX_JSON = 1024 * 1024


def _sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while content := stream.read(1024 * 1024):
            result.update(content)
    return result.hexdigest()


def _write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def validate_snapshot(record, *, root):
    """Validate frozen outputs, not the mutable original dependency locations."""
    root = Path(root).resolve()
    if record.get('protocol') != PROTOCOL or record.get('status') != 'ready':
        raise ValueError('Image snapshot is not ready')
    files = [(record['output_scene'], record['output_sha256']),
             *((image['frozen_path'], image['sha256']) for image in record['images'])]
    if 'glb' in record:
        files.append((record['glb']['output'], record['glb']['output_sha256']))
        files.extend((item['frozen_path'], item['sha256']) for item in record['glb'].get('resources', []))
    for path, digest in files:
        path = Path(path)
        if not path.is_absolute() or not path.is_relative_to(root):
            raise ValueError('Frozen image snapshot path escapes its root')
        current = root
        for part in path.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('Frozen image snapshot contains a symlink component')
        if not path.resolve().is_relative_to(root) or not path.is_file() or _sha(path) != digest:
            raise ValueError('Frozen image snapshot output is missing, changed or outside trusted root')
    return True


def snapshot_images(blender, source, output, *, authority, frames=(1,), timeout=60., deadline=None, glb_source=None):
    budget = DeadlineBudget.start(timeout, deadline=deadline)
    if budget.exhausted:
        raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'No resource worker launched after deadline')
    source, output, blender = Path(source), Path(output), Path(blender)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != '.blend' or output.exists():
        raise ValueError('Invalid image snapshot source or non-fresh output directory')
    if os.name != 'posix' or not blender.is_file() or not os.access(blender, os.X_OK):
        raise InspectionFailure('infrastructure_error', 'RESOURCE_WORKER_UNAVAILABLE', 'Executable Blender and POSIX process groups required')
    if type(frames) is not tuple or not 1 <= len(frames) <= 16 or any(type(frame) is not int or frame < 0 for frame in frames):
        raise ValueError('Invalid native dependency frame scope')
    output.mkdir(parents=True)
    source, output, blender = source.resolve(), output.resolve(), blender.resolve()
    source_hash = _sha(source)
    request = {'protocol': PROTOCOL, 'source': str(source), 'source_sha256': source_hash,
               'output': str(output / 'snapshot'), 'authority': authority, 'frames': list(frames)}
    if glb_source is not None:
        glb_source = Path(glb_source)
        if glb_source.is_symlink() or not glb_source.is_file() or glb_source.suffix.lower() != '.glb':
            raise ValueError('Invalid GLB input to dependency snapshot')
        request.update(glb_source=str(glb_source.resolve()), glb_source_sha256=_sha(glb_source))
    encoded = json.dumps(request, sort_keys=True, allow_nan=False).encode()
    if len(encoded) > MAX_JSON:
        raise ValueError('Image snapshot request size limit')
    request_path, result_path = output / 'request.json', output / 'result.json'
    request_path.write_bytes(encoded)
    request_hash = hashlib.sha256(encoded).hexdigest()
    record_path = output / 'worker_record.json'
    worker = {'protocol': PROTOCOL, 'status': 'not_started', 'request_sha256': request_hash,
              'deadline_monotonic': budget.deadline, 'containment': 'trusted_process_group_not_security_sandbox',
              'cleanup_limit_seconds': 2., 'cost_scope': 'native_image_and_core_glb_dependency_snapshot',
              'worker_sha256': _sha(WORKER), 'resource_module_sha256': _sha(Path(__file__).with_name('l1_resources.py'))}
    _write(record_path, worker)
    if budget.exhausted:
        worker.update(status='budget_exhausted', budget=budget.record('resource_snapshot'))
        _write(record_path, worker)
        raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'Resource setup exceeded shared deadline')
    environment = {key: value for key, value in os.environ.items()
                   if key in {'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'TEMP', 'TMP', 'SYSTEMROOT'}}
    environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    command = [str(blender), '--background', '--factory-startup', '--disable-autoexec', '-noaudio', '--threads', '2',
               '--python-exit-code', '1', '--python', str(WORKER), '--', '--request', str(request_path), '--result', str(result_path)]
    process, timed_out, reaped = None, False, True
    try:
        with (output / 'worker.log').open('w') as log:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=output, env=environment, start_new_session=True)
            worker.update(status='running', pid=process.pid)
            _write(record_path, worker)
            try:
                process.wait(timeout=budget.remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
    except (KeyboardInterrupt, SystemExit):
        worker['status'] = 'interrupted'
        raise
    except OSError as error:
        worker['status'] = 'launch_error'
        raise InspectionFailure('infrastructure_error', 'RESOURCE_WORKER_LAUNCH_ERROR', str(error)) from error
    finally:
        cleanup = time.monotonic()
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                reaped = False
            worker.update(return_code=process.returncode, leader_reaped=reaped, group_kill_sent=True)
        worker.update(cleanup_seconds=time.monotonic() - cleanup, budget=budget.record('resource_snapshot'))
        if timed_out or budget.exhausted:
            worker['status'] = 'budget_exhausted'
        _write(record_path, worker)
    if not reaped:
        raise InspectionFailure('infrastructure_error', 'RESOURCE_CLEANUP_TIMEOUT', 'Resource worker leader not reaped')
    if timed_out or budget.exhausted:
        raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'Resource worker terminated at shared deadline')
    try:
        if process.returncode != 0 or not result_path.is_file() or result_path.stat().st_size > MAX_JSON:
            raise ValueError('Resource worker failed or returned absent/oversized output')
        result = json.loads(result_path.read_text())
        if (not isinstance(result, dict) or result.get('protocol') != PROTOCOL or result.get('request_sha256') != request_hash
                or result.get('source_sha256') != source_hash or result.get('frames') != list(frames)
                or result.get('status') not in {'ready', 'not_measurable'}
                or _sha(source) != source_hash or _sha(request_path) != request_hash
                or _sha(WORKER) != worker['worker_sha256']
                or _sha(Path(__file__).with_name('l1_resources.py')) != worker['resource_module_sha256']):
            raise ValueError('Invalid source/request/frame binding in resource response')
        if result['status'] == 'ready':
            if result['authority'] != authority or result['authority_sha256'] != hashlib.sha256(
                    json.dumps(authority, sort_keys=True, allow_nan=False).encode()).hexdigest():
                raise ValueError('Resource authority drifted')
            validate_snapshot(result, root=output / 'snapshot')
            if glb_source is not None and (result.get('glb', {}).get('source_sha256') != request['glb_source_sha256']
                                           or _sha(glb_source) != request['glb_source_sha256']):
                raise ValueError('GLB source binding changed during resource freezing')
            if glb_source is not None and (result['glb'].get('protocol') != 'l1-glb-resource-snapshot-v1'
                                           or result['glb'].get('authority_sha256') != result['authority_sha256']):
                raise ValueError('GLB dependency authority or protocol mismatch')
    except (OSError, KeyError, TypeError, ValueError) as error:
        worker.update(status='protocol_error', reason=str(error))
        _write(record_path, worker)
        raise InspectionFailure('infrastructure_error', 'RESOURCE_WORKER_PROTOCOL_ERROR', str(error)) from error
    if budget.exhausted:
        worker.update(status='budget_exhausted', budget=budget.record('resource_snapshot'))
        _write(record_path, worker)
        raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'Resource validation exceeded shared deadline')
    worker.update(status='completed', result_sha256=_sha(result_path), budget=budget.record('resource_snapshot'))
    _write(record_path, worker)
    if budget.exhausted:
        worker.update(status='budget_exhausted', budget=budget.record('resource_snapshot'))
        _write(record_path, worker)
        raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'Resource finalization exceeded shared deadline')
    return {**result, 'resource_execution': {**worker, 'record_path': str(record_path)}}
