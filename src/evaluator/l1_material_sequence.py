"""No-bitmap measurements on every declared native state in one load session."""
from __future__ import annotations

from pathlib import Path

from .l1_failures import InspectionFailure, record_failure

PROTOCOL = 'l1-material-sequence-v1'
METRIC = 'procedural_material_sequence'


def validate_parameters(check, spec):
    if (spec.profile != 'L1' or check.params['path'] != '/material_sequences/native'
            or check.params['frames'] not in ([1], [1, 61, 1], [1, 31, 61, 91, 121, 1])
            or check.params['frames'] == [1, 31, 61, 91, 121, 1] and
                spec.to_dict().get('l1_image_quality', {}).get('version') != 'l1-reference-visual-v2.0.0'
            or any(type(frame) is not int for frame in check.params['frames'])
            or sum(c.applicable and c.metric == METRIC for group in spec.checks.values() for c in group) != 1
            or check.id not in spec.critical_constraints or check.pass_threshold != 1
            or check.role != 'standard'):
        raise ValueError('Material sequence requires the L1 native declared-state critical gate')


def collect_material_sequences(spec, evidence, paths, output, *, task_id, blender, spec_path, timeout, deadline):
    from harness.L1.common.reproduction import frame_policy

    from .l1_file_io import run_file_io
    from .l1_inspection_receipt import validate_inspection
    from .l1_runner import _inspect

    checks = [c for group in spec.checks.values() for c in group if c.applicable and c.metric == METRIC]
    if not checks:
        return
    pointer = '/material_sequences/native'
    try:
        frames = frame_policy(task_id, spec)['native_frames']
        if len(checks) != 1 or checks[0].params['frames'] != frames:
            raise ValueError('Material sequence does not match task-owned state policy')
        source = paths.get(spec.scene)
        if source is None:
            raise InspectionFailure('not_measurable', 'MATERIAL_SEQUENCE_SOURCE_MISSING', 'Native scene unavailable')
        directory = output / 'material_sequence'
        observed = _inspect(blender, source, spec_path, directory, timeout,
                            views=False, frames=tuple(frames), deadline=deadline)
        validation = validate_inspection(observed, scene=source, spec=spec_path, deadline=deadline, frames=tuple(frames))
        binding = run_file_io('hash', {'path': str(directory / 'facts.json')},
                              output=output / 'file_io', deadline=deadline)
        sequence = observed['state_sequence']
        evidence['material_sequences'] = {'native': {
            'protocol': PROTOCOL, 'spec_sha256': spec.digest,
            'source_sha256': sequence['scene_sha256'], 'frames': frames,
            'session': {key: sequence[key] for key in ('protocol', 'session_id', 'process_id', 'file_loads',
                'scene_path', 'scene_sha256', 'spec_sha256', 'frames', 'autoexec_enabled', 'status')},
            'snapshots': [{'index': item['index'], 'frame': item['frame'], 'observed_frame': item['observed_frame'],
                           'audit': item['scene']['procedural_materials']} for item in sequence['snapshots']],
            'inspector_execution': observed.get('inspector_execution'),
            'inspector_persistence': observed.get('inspector_persistence'), 'inspection_validation': validation,
            'facts_path': str(directory / 'facts.json'), 'facts_sha256': binding['sha256'], 'binding_io': binding,
        }}
    except (InspectionFailure, OSError, ValueError, KeyError, TypeError) as error:
        failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
            'infrastructure_error', 'MATERIAL_SEQUENCE_UNAVAILABLE', str(error))
        row = {'protocol': PROTOCOL, 'status': failure.status, 'reason': str(failure)}
        for key in ('inspector_execution', 'inspector_persistence', 'inspection_validation_io'):
            if hasattr(error, key):
                row[key] = getattr(error, key)
        evidence['material_sequences'] = {'native': row}
        record_failure(spec, evidence, [pointer], failure)


def measure(check, evidence, spec):
    from .l1_seed_quality import _bound_bytes
    from .metrics import MissingEvidence, procedural_materials, resolve
    from .spec import CheckSpec

    def require(condition, reason):
        if not condition:
            raise MissingEvidence('Material sequence: ' + reason)

    row = resolve(evidence, check.params['path'])
    frames = check.params['frames']
    source = evidence.get('artifacts', {}).get(spec.scene, {}).get('sha256')
    require(row.get('protocol') == PROTOCOL and row.get('spec_sha256') == spec.digest
            and row.get('frames') == frames and source and row.get('source_sha256') == source,
            'source/spec/frame binding missing')
    session = row.get('session', {})
    require(session.get('protocol') == 'l1-state-sequence-v1' and session.get('status') == 'completed'
            and type(session.get('file_loads')) is int and session.get('file_loads') == 1
            and session.get('autoexec_enabled') is False
            and session.get('scene_sha256') == source and session.get('frames') == frames
            and row.get('inspection_validation', {}).get('status') == 'verified' and row.get('inspector_execution')
            and session.get('process_id') == row['inspector_execution'].get('pid'),
            'single-session inspection binding missing')
    snapshots = row.get('snapshots', [])
    require(len(snapshots) == len(frames), 'missing declared state')
    facts = _bound_bytes(row['facts_path'], row['facts_sha256'],
                         Path(row['inspector_execution']['record_path']).parent, decode=True)
    recorded = facts.get('state_sequence', {})
    require(all(recorded.get(key) == value for key, value in session.items()), 'session differs from raw inspector facts')
    raw_snapshots = [{'index': item['index'], 'frame': item['frame'], 'observed_frame': item['observed_frame'],
                      'audit': item['scene']['procedural_materials']} for item in recorded.get('snapshots', [])]
    require(snapshots == raw_snapshots, 'audits differ from raw inspector facts')
    result = []
    atomic = CheckSpec.parse({'id': 'state_material', 'group': 'state_material', 'metric': 'procedural_materials',
                             'params': {'path': '/audit'}})
    for index, (snapshot, frame) in enumerate(zip(snapshots, frames, strict=True)):
        require(snapshot.get('index') == index and snapshot.get('frame') == frame
                and snapshot.get('observed_frame') == frame and snapshot.get('audit', {}).get('frame') == frame,
                'state order or observed frame mismatch')
        score, audit = procedural_materials(atomic, {'audit': snapshot['audit']}, spec)
        result.append({'index': index, 'frame': frame, 'passed': bool(score), 'audit': audit})
    passed = all(item['passed'] for item in result)
    return float(passed), {'protocol': PROTOCOL, 'passed': passed, 'frames': frames, 'snapshots': result,
                           'source_sha256': source, 'session_id': session['session_id'],
                           'facts_path': row['facts_path'], 'facts_sha256': row['facts_sha256'],
                           'scope': 'Actual dependencies in declared states only; not intermediate animation or correct appearance'}
