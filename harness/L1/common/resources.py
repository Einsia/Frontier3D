"""L1 raw-delivery to image-self-contained comparison snapshots.

Original outputs remain immutable evidence. A trusted derived native scene may
pack authorized image bytes; both raw and comparison hashes are retained.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from harness.L1.common.attempt_log import sha256, write_json_atomic
from harness.L1.common.reproduction import frame_policy
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_resource_runner import snapshot_images, validate_snapshot


def declared_authority(*, source_root, snapshot_root, metadata):
    source_root, snapshot_root = Path(source_root).resolve(), Path(snapshot_root).resolve()
    return {'protocol': 'l1-resource-authority-v1', 'mode': 'declared_files',
            'origin_scene': str(source_root / 'scene.blend'), 'storage_root': str(snapshot_root),
            'files': {str(source_root / name): {'path': str(snapshot_root / name), 'sha256': data['sha256']}
                      for name, data in metadata['files'].items()}}


def generated_authority(workspace):
    workspace = Path(workspace).resolve()
    return {'protocol': 'l1-resource-authority-v1', 'mode': 'generated_workspace',
            'origin_scene': str(workspace / 'scene.blend'), 'storage_root': str(workspace)}


def freeze_comparison_artifacts(*, blender, artifacts, output, authority, task_id, timeout, deadline):
    """Freeze both scene formats under the inherited total deadline, once."""
    started = time.monotonic()
    output = Path(output)
    record = {'protocol': 'l1-comparison-artifacts-v1', 'status': 'not_measurable', 'task_id': task_id,
              'raw_artifacts': {name: str(path) for name, path in artifacts.items()},
              'raw_sha256': {}, 'artifacts': {}, 'artifact_sha256': {}, 'cost_seconds': 0.,
              'record_path': str(output / 'record.json'), 'execution_attempted': False, 'call_attempted': False}
    output.mkdir(parents=True, exist_ok=False)
    write_json_atomic(output / 'record.json', record)
    try:
        if time.monotonic() >= deadline:
            raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'No resource freezing after shared deadline')
        for name in ('scene.blend', 'scene.glb'):
            path = Path(artifacts[name])
            if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
                raise ValueError('Missing or invalid raw artifact for resource freezing')
            record['raw_sha256'][name] = sha256(path)
        record['call_attempted'] = True
        write_json_atomic(output / 'record.json', record)
        snapshot = snapshot_images(blender, artifacts['scene.blend'], output / 'image_snapshot', authority=authority,
                                   frames=tuple(frame_policy(task_id)['native_frames']), timeout=timeout, deadline=deadline,
                                   glb_source=artifacts['scene.glb'])
        record['snapshot'] = snapshot
        if snapshot['status'] != 'ready':
            raise ValueError(snapshot.get('reason', 'Image resource snapshot unavailable'))
        for name, path in [('scene.blend', snapshot['output_scene']), ('scene.glb', snapshot['glb']['output'])]:
            record['artifacts'][name] = path
            record['artifact_sha256'][name] = sha256(Path(path))
        if any(sha256(Path(artifacts[name])) != value for name, value in record['raw_sha256'].items()):
            raise ValueError('Raw artifacts changed during image freezing')
        if time.monotonic() >= deadline:
            raise InspectionFailure('infrastructure_error', 'EVALUATION_BUDGET_EXHAUSTED', 'Late resource completion rejected')
        record['status'] = 'ready'
    except (InspectionFailure, OSError, KeyError, TypeError, ValueError) as error:
        record['failure'] = {'reason': str(error), 'code': getattr(error, 'code', 'RESOURCE_SNAPSHOT_UNAVAILABLE')}
        record['status'] = 'budget_exhausted' if getattr(error, 'code', None) == 'EVALUATION_BUDGET_EXHAUSTED' else 'not_measurable'
    except (KeyboardInterrupt, SystemExit) as error:
        record.update(status='interrupted', failure={'reason': type(error).__name__, 'code': 'RESOURCE_INTERRUPTED'})
        raise
    finally:
        worker_path = output / 'image_snapshot/worker_record.json'
        if worker_path.is_file() and not worker_path.is_symlink() and worker_path.stat().st_size <= 1024 * 1024:
            try:
                worker = json.loads(worker_path.read_text())
                record['execution_attempted'] = type(worker.get('pid')) is int and worker['pid'] > 0
                record['worker_record'] = str(worker_path)
                record['worker_record_sha256'] = sha256(worker_path)
                record['worker_status'] = worker.get('status')
            except (OSError, AttributeError, TypeError, ValueError):
                record['worker_record_error'] = 'Worker receipt absent or invalid; execution count not assumed'
        record['cost_seconds'] = time.monotonic() - started
        write_json_atomic(output / 'record.json', record)
    if record['status'] == 'ready' and time.monotonic() >= deadline:
        record.update(status='budget_exhausted', failure={'code': 'EVALUATION_BUDGET_EXHAUSTED',
                                                        'reason': 'Resource record persistence exceeded shared deadline'})
        write_json_atomic(output / 'record.json', record)
    return record


def comparison_artifacts_intact(record):
    try:
        if record.get('protocol') != 'l1-comparison-artifacts-v1' or record.get('status') != 'ready':
            return False
        if set(record['artifacts']) != {'scene.blend', 'scene.glb'} or set(record['artifact_sha256']) != set(record['artifacts']):
            return False
        root = Path(record['record_path']).parent
        validate_snapshot(record['snapshot'], root=root)
        return all(sha256(Path(path)) == record['artifact_sha256'][name] for name, path in record['artifacts'].items())
    except (OSError, KeyError, TypeError, ValueError):
        return False


def comparison_binding(record):
    """Bind the immutable resource receipt separately from raw scene hashes."""
    return {'protocol': record['protocol'], 'record_path': record['record_path'],
            'record_sha256': sha256(Path(record['record_path'])),
            'raw_sha256': dict(record['raw_sha256']),
            'artifact_sha256': dict(record['artifact_sha256'])}


def bound_comparison_intact(record, binding):
    """Detect receipt, worker evidence, raw-output and frozen-output drift.

    Mutable original image locations are intentionally not reopened: their
    authorized frozen bytes are the comparison input. This is not a sandbox.
    """
    try:
        receipt = Path(record['record_path'])
        if receipt.is_symlink() or not receipt.is_file() or comparison_binding(record) != binding:
            return False
        if not comparison_artifacts_intact(record):
            return False
        for name, digest in record['raw_sha256'].items():
            path = Path(record['raw_artifacts'][name])
            if path.is_symlink() or not path.is_file() or sha256(path) != digest:
                return False
        worker_path = Path(record['worker_record'])
        if worker_path.is_symlink() or sha256(worker_path) != record['worker_record_sha256']:
            return False
        worker = record['snapshot']['resource_execution']
        for name in ('request', 'result'):
            path = worker_path.with_name(f'{name}.json')
            if path.is_symlink() or sha256(path) != worker[f'{name}_sha256']:
                return False
        return True
    except (OSError, KeyError, TypeError, ValueError):
        return False
