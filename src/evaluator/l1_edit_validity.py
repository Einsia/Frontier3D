"""CodeEdit validity and material content, separate from geometric quality."""
from __future__ import annotations

UNKNOWN = {'not_measurable', 'not_implemented', 'infrastructure_error'}
MATERIAL_METRICS = {'procedural_materials', 'procedural_material_sequence'}
BITMAP_CODES = {'BITMAP_NODE', 'BITMAP_SOCKET', 'BITMAP_TEXTURE',
                'BITMAP_GROUP_INPUT', 'BITMAP_MODIFIER', 'MOVIE_CLIP_NODE'}


def combine(statuses):
    statuses = list(statuses)
    # An independently confirmed violation remains a violation when another
    # measurement is unavailable. Unknown by itself is never a failure.
    for status in ('failed', 'infrastructure_error', 'not_implemented', 'not_measurable'):
        if status in statuses:
            return status
    return 'passed' if statuses and all(s == 'passed' for s in statuses) else 'not_measurable'


def gate(status, **details):
    return {'passed': status == 'passed', 'measurement_status': status, **details}


def reproduction(spec, evidence):
    from .l1_image_quality import visual_only
    if visual_only(spec.to_dict()):
        from .l1_image_execution import measure_execution
        return measure_execution(spec, evidence)
    rows = {}
    runs = evidence.get('harness', {}).get('seed_runs', {})
    for seed in map(str, spec.seeds):
        run = runs.get(seed, {})
        semantic = run.get('reproduction_status')
        if run.get('passed') is False:
            status, reason = 'failed', 'Seed execution failed'
        elif run.get('passed') is not True:
            status, reason = 'not_measurable', 'Seed execution evidence missing'
        elif semantic == 'failed':
            status, reason = 'passed', 'Measured geometry mismatch is quality evidence; seed execution passed'
        elif semantic == 'ok':
            status, reason = 'passed', 'Measured reproduction matched'
        else:
            status = semantic if semantic in UNKNOWN else 'not_measurable'
            reason = 'Reproduction measurement unavailable; not a measured mismatch'
        rows[seed] = {'status': status, 'execution_passed': run.get('passed'),
                      'reproduction_status': semantic, 'reason': reason}
    status = combine(row['status'] for row in rows.values())
    return float(status == 'passed'), {'measurement_status': status, 'per_seed': rows,
        'outcomes': {k: True if r['status'] == 'passed' else False if r['status'] == 'failed' else None
                     for k, r in rows.items()}, 'semantic_reproduction_required': False,
        'geometry_equality_affects_eligibility': False}


def _audits(row):
    details = row.get('details', {})
    if row['metric'] == 'procedural_material_sequence':
        return [s.get('audit', {}) for s in details.get('snapshots', [])]
    return [details] if details.get('protocol') == 'l1-procedural-materials-v1' else []


def material(row):
    """Only known bitmap dependencies invalidate; missing assignments are content."""
    statuses, assignments, content, forbidden = [], [], [], []
    audits = _audits(row)
    for audit in audits:
        violations = audit.get('violations', [])
        bitmap = [r for r in violations if r.get('code') in BITMAP_CODES]
        unassigned = [r for r in violations if r.get('code') == 'UNASSIGNED_SURFACE']
        other = [r for r in violations if r.get('code') not in BITMAP_CODES | {'UNASSIGNED_SURFACE'}]
        unknown = audit.get('unknown', [])
        count = audit.get('material_uses')
        well_formed = (audit.get('protocol') == 'l1-procedural-materials-v1'
                       and type(count) is int and count > 0
                       and audit.get('status') in {'passed', 'failed', 'not_measurable'})
        statuses.append('failed' if bitmap else 'not_measurable' if not well_formed or other or unknown
                        or audit.get('status') == 'not_measurable' else 'passed')
        assignments.append(max(0., 1 - len({r.get('owner') for r in unassigned}) / count)
                           if well_formed else None)
        content.extend(unassigned)
        forbidden.extend(bitmap)
    original = row.get('measurement_status', row.get('status', 'not_measurable'))
    if not audits:
        # A trusted passed metric already validated a complete audit. A failed
        # verdict without its cause cannot be relabelled as confirmed cheating.
        statuses = [original if original in UNKNOWN | {'passed'} else 'not_measurable']
        assignments = [1. if original == 'passed' else None]
    elif original in UNKNOWN:
        statuses.append(original)
    return {**gate(combine(statuses)), 'assignment_score': min(assignments)
            if assignments and all(v is not None for v in assignments) else None,
            'content_issues': content, 'forbidden_dependencies': forbidden,
            'meaning': 'Bitmap dependency is a system violation; unassigned surface is content only'}


def system_gate(row):
    if row['metric'] in MATERIAL_METRICS:
        return material(row)
    status = row.get('measurement_status', row.get('status', 'not_measurable'))
    return gate(status, details=row.get('details', {}))


def assignment_score(checks):
    scores = [material(row)['assignment_score'] for row in checks.values()
              if row['metric'] in MATERIAL_METRICS]
    return min(scores) if scores and all(v is not None for v in scores) else None
