"""Task-owned quality checks on every seed, independent of reproducibility.

Only trusted orchestrator records enter this API. File/hash checks bind an
existing evaluator report; they do not authenticate candidate-authored JSON.
Consumption runs inside the deadline-bounded L1 scoring worker.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from statistics import mean

PROTOCOL = 'l1-seed-quality-v1'
METRIC = 'all_seed_checks'
MEASUREMENTS = frozenset({'procedural_materials', 'machined_sleeve', 'washer_edit', 'swept_bar', 'slot_plate_edit',
                          'native_image_pair', 'main_render_consistency', 'procedural_material_sequence'})
# Three declared states plus the initial state can exceed 64 MiB for valid,
# detailed scenes. Keep a finite cap aligned with inspector/receipt readers.
MAX_JSON_BYTES = 256 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024


def selected_checks(spec):
    image_policy = spec.to_dict().get('l1_image_quality')
    if image_policy:
        from .l1_image_quality import selected_ids
        ids = selected_ids(image_policy)
        return {c.id:c for group in spec.checks.values() for c in group if c.id in ids}
    policy = spec.to_dict().get('l1_edit_quality')
    if policy:
        from .l1_edit_quality import selected_ids
        ids = selected_ids(policy)
        return {c.id:c for group in spec.checks.values() for c in group if c.id in ids}
    return {c.id: c for group in spec.checks.values() for c in group
            if c.applicable and c.metric in MEASUREMENTS}


def quality_check(spec):
    return next((c for group in spec.checks.values() for c in group
                 if c.applicable and c.metric == METRIC), None)


def validate_parameters(check, spec):
    selected = selected_checks(spec)
    frames = check.params['native_frames']
    sequences = [c for c in selected.values() if c.metric == 'procedural_material_sequence']
    if (spec.profile != 'L1' or not spec.seeds or not selected
            or sum(c.applicable and c.metric == METRIC for g in spec.checks.values() for c in g) != 1
            or check.id not in spec.critical_constraints or check.role != 'standard'
            or check.pass_threshold != 1
            or check.params['checks'] != sorted(selected)
            or frames not in ([1], [1, 61, 1], [1, 31, 61, 91, 121, 1])
            or frames == [1, 31, 61, 91, 121, 1] and
                spec.to_dict().get('l1_image_quality', {}).get('version') != 'l1-reference-visual-v2.0.0'
            or any(type(frame) is not int for frame in frames)
            or check.params['glb_frames'] != [1]
            or sequences and (len(sequences) != 1 or sequences[0].params['frames'] != frames)
            # Image checks have their own explicit saved-view frame (currently
            # frame 1). They do not claim to measure the exploded appearance.
            # State material checks still cover the complete declared sequence.
            # Numerical pilots remain static until they have state-aware methods.
            or frames != [1] and (not sequences or any(c.metric in {'machined_sleeve', 'washer_edit', 'swept_bar', 'slot_plate_edit'}
                for c in selected.values()))):
        raise ValueError('All-seed quality requires the exact L1 measurement/state check set and a critical gate')


def _require(value, reason):
    from .metrics import MissingEvidence
    if not value:
        raise MissingEvidence('Seed quality: ' + reason)


def _digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _bound_bytes(path, digest, root, *, decode=False):
    """Bounded regular-file read/hash; no links, devices or paths outside run."""
    path, root = Path(path), Path(root)
    _require(path.is_absolute() and root.is_absolute() and '..' not in path.parts
             and path.is_relative_to(root) and _digest(digest), 'invalid file/root/hash binding')
    for parent in [path, *path.parents]:
        _require(not parent.is_symlink(), 'symlink in evaluator evidence path')
    limit = MAX_JSON_BYTES if decode else MAX_ARTIFACT_BYTES
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit,
                 'nonregular, empty or oversized evidence')
        hasher, pieces, size = hashlib.sha256(), [], 0
        while block := stream.read(min(1024 * 1024, limit + 1 - size)):
            size += len(block)
            _require(size <= limit, 'evidence grew beyond capacity')
            hasher.update(block)
            if decode:
                pieces.append(block)
        after = os.fstat(stream.fileno())
        _require((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                 == (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                 and hasher.hexdigest() == digest, 'file changed or digest mismatch')
    return json.loads(b''.join(pieces)) if decode else None


def seed_report_summary(report, spec, expected_hashes, *, task_id, evidence=None):
    """Extract measured checks, never a seed report's recursive aggregate gate."""
    from .spec import EVALUATOR_VERSION
    _require(report.get('evaluator_version') == EVALUATOR_VERSION
             and report.get('spec_sha256') == spec.digest
             and report.get('task_id') == task_id
             and report.get('artifact_sha256') == expected_hashes,
             'report identity or execution artifacts mismatch')
    _require(report.get('scoring_failed') is False and report.get('budget_exhausted') is False,
             'seed evaluator failed or exceeded its budget')
    receipt = report.get('compute_execution', {})
    _require(receipt.get('operation') == 'score' and receipt.get('status') == 'completed'
             and receipt.get('cleanup_ack') is True and receipt.get('leader_reaped') is True,
             'seed score has no completed compute receipt')
    selected = selected_checks(spec)
    rows = [c for group in report.get('modules', {}).values() for c in group.get('checks', [])
            if c.get('id') in selected]
    _require(len(rows) == len(selected) and {c['id'] for c in rows} == set(selected),
             'seed report is missing checks or contains duplicates')
    summary = {}
    quality_rows = {}
    edit_policy = spec.to_dict().get('l1_edit_quality')
    image_policy = spec.to_dict().get('l1_image_quality')
    policy = edit_policy or image_policy
    for row in rows:
        definition = selected[row['id']]
        _require(row.get('metric') == definition.metric and row.get('params') == definition.params
                 and row.get('pass_threshold') == definition.pass_threshold,
                 'seed check definition changed')
        # Reports remain immutable. Reinterpret the old boolean reproduction
        # metric from its hash-bound score input, never from a candidate claim.
        if policy and row['metric'] == 'seed_success' and evidence is not None:
            from .l1_edit_validity import reproduction
            score, details = reproduction(spec, evidence)
            row = {**row, 'score':score, 'details':details,
                   'measurement_status':details['measurement_status'], 'passed':bool(score)}
        status, score = row.get('measurement_status'), row.get('score')
        allowed = {'passed', 'failed', 'not_measurable', 'not_implemented', 'infrastructure_error'} if policy else {'passed', 'failed'}
        _require(status in allowed, 'seed check is unavailable: ' + row['id'])
        _require(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1
                 and row.get('passed') is (status == 'passed'), 'inconsistent seed verdict')
        summary[row['id']] = {'metric': definition.metric, 'status': status,
                              'score':score if status in {'passed','failed'} else None,
                              **({'details':row.get('details',{})} if policy else {})}
        quality_rows[row['id']] = row
    # These checks cover real deliverables and trusted execution. Requirements,
    # critical_constraints and S_core include this all-seed gate and therefore
    # must not be used recursively while collecting its inputs.
    gate_names = ('execution', 'artifacts', 'real_geometry', 'integrity')
    if not image_policy:
        gate_names += ('infrastructure',)
    gates = {name: report.get('gates', {}).get(name, {}) for name in gate_names}
    allowed = {'passed','failed','not_measurable','not_implemented','infrastructure_error'} if policy else {'passed','failed'}
    _require(all(g.get('measurement_status') in allowed for g in gates.values()),
             'seed prerequisite evidence unavailable')
    passed = all(r['status'] == 'passed' for r in summary.values()) and all(g.get('passed') is True for g in gates.values())
    edit = None
    extra = {}
    if policy:
        from .l1_edit_quality import components
        from .l1_edit_validity import combine, system_gate
        if edit_policy:
            edit = components(policy,quality_rows)
        # Content errors reduce the weighted quality, never the system gate.
        system = {n:system_gate(quality_rows[n]) for n in policy['system_checks']}
        status = combine(g['measurement_status'] for g in [*gates.values(), *system.values()])
        if image_policy:
            from .l1_image_quality import image_score
            measured_image = image_score(image_policy, quality_rows)
            status = combine([status, 'passed' if measured_image is not None else 'not_measurable'])
        passed = status == 'passed'
        extra = {'system_checks':system, 'prerequisites':gates,
                 'unverified_checks':[n for n,r in summary.items() if r['status'] not in {'passed','failed'}]}
    image = [r['score'] for r in summary.values() if r['metric'] == 'native_image_pair']
    return {'status': status if policy else 'passed' if passed else 'failed', 'checks': summary, **extra,
            **({'edit_components':edit} if edit is not None else {}),
            'failed_prerequisites': [name for name, gate in gates.items() if gate.get('passed') is not True],
            'image_score': measured_image if image_policy else mean(image) if image else None}


def measure(check, evidence, spec):
    record = evidence.get('harness', {}).get('seed_quality')
    _require(isinstance(record, dict), 'trusted per-seed quality record missing')
    expected = [str(seed) for seed in spec.seeds]
    selected = sorted(selected_checks(spec))
    _require(record.get('protocol') == PROTOCOL and record.get('spec_sha256') == spec.digest
             and record.get('checks') == selected and record.get('expected_seeds') == list(spec.seeds)
             and record.get('native_frames') == check.params['native_frames']
             and record.get('glb_frames') == check.params['glb_frames'], 'protocol/spec/check/frame mismatch')
    per_seed = record.get('per_seed')
    _require(isinstance(per_seed, dict) and set(per_seed) == set(expected), 'missing or unexpected seed')
    root = Path(record['run_root'])
    summaries = {}
    for seed in expected:
        row = per_seed[seed]
        _require(isinstance(row, dict) and row.get('status') == 'collected', 'seed ' + seed + ' was not measured')
        run = evidence.get('harness', {}).get('seed_runs', {}).get(seed, {})
        hashes = row.get('artifact_sha256')
        _require(run.get('passed') is True and isinstance(hashes, dict)
                 and set(hashes) == set(spec.required_artifacts) and hashes == run.get('artifact_sha256'),
                 'seed execution hashes do not match')
        submission = Path(row['submission_root'])
        _require(submission.is_relative_to(root / ('seed-' + seed)), 'seed directory mismatch')
        for name, digest in hashes.items():
            _bound_bytes(submission / name, digest, root)
        report = _bound_bytes(row['report']['path'], row['report']['sha256'], submission / 'evaluation', decode=True)
        _require(report.get('evidence_path') == row['evidence']['path'], 'report/evidence path mismatch')
        _bound_bytes(row['evidence']['path'], row['evidence']['sha256'], Path(row['report']['path']).parent)
        receipt, validation = report.get('compute_execution', {}), row.get('compute_validation', {})
        _require(validation.get('status') == 'completed' and validation.get('persistence_ack') is True
                 and validation.get('immutable_state_history') is True
                 and validation.get('result_sha256') == receipt.get('result_sha256')
                 and validation.get('request_sha256') == receipt.get('request_sha256'),
                 'score compute receipt was not independently validated')
        work = Path(receipt['record_path']).parent
        report_root = Path(row['report']['path']).parent
        raw = _bound_bytes(work / 'result.json', receipt['result_sha256'], report_root, decode=True)
        _require(raw.get('protocol') == 'l1-compute-v1' and raw.get('operation') == 'score'
                 and all(raw.get('result', {}).get(key) == report.get(key)
                         for key in ('modules', 'gates', 'spec_sha256')), 'score/result disagreement')
        request = _bound_bytes(work / 'request.json', receipt['request_sha256'], report_root, decode=True)
        from .spec import EvalSpec
        payload = request.get('payload', {})
        _require(request.get('protocol') == 'l1-compute-v1' and request.get('operation') == 'score'
                 and EvalSpec.from_dict(payload.get('spec', {})).digest == spec.digest
                 and {name: value.get('sha256') for name, value in payload.get('evidence', {}).get('artifacts', {}).items()}
                 == hashes, 'seed score input binding mismatch')
        summary = seed_report_summary(report, spec, hashes, task_id=record['task_id'], evidence=payload['evidence'])
        summaries[seed] = {**summary, 'report': row['report'], 'evidence': row['evidence']}
    images = [r['image_score'] for r in summaries.values() if r['image_score'] is not None]
    passed = all(r['status'] == 'passed' for r in summaries.values())
    extra = {}
    if any(spec.to_dict().get(k) for k in ('l1_edit_quality','l1_image_quality')):
        from .l1_edit_validity import combine
        extra['measurement_status'] = combine(r['status'] for r in summaries.values())
    return float(passed), {'protocol': PROTOCOL, 'passed': passed, 'per_seed': summaries, **extra,
                           'minimum_image_score': min(images) if images else None,
                           'scope': 'Listed measurements on every seed; native material states follow the task, GLB is static; no semantic completion'}
