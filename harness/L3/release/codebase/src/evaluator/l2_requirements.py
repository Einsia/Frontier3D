"""Task requirements and threshold provenance, separate from automatic scores."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def load_requirements(path, spec, task_id=None, instruction=None):
    raw = json.loads(Path(path).read_text())
    if raw.get('schema_version') != 1 or raw.get('spec_sha256') != spec.digest:
        raise ValueError('Requirements must bind the current EvalSpec')
    if task_id is not None and raw.get('task_id') != task_id:
        raise ValueError('Requirements task mismatch')
    if instruction is not None and raw.get('instruction_sha256') != hashlib.sha256(instruction.encode()).hexdigest():
        raise ValueError('Requirements instruction mismatch')
    checks = {c.id: c for module in spec.checks.values() for c in module}
    if set(raw.get('checks', {})) != set(checks):
        raise ValueError('Requirements must map every automatic check exactly once')
    for name, rule in raw['checks'].items():
        if rule.get('source_kind') not in {'instruction', 'runtime_contract', 'heuristic'}:
            raise ValueError('Invalid threshold source')
        if type(rule.get('public')) is not bool or not rule.get('rationale'):
            raise ValueError('Missing public visibility or rationale')
        if rule.get('calibration') not in {'explicit', 'pending_human', 'reviewed'}:
            raise ValueError('Invalid calibration state')
        if rule['public'] and (rule['source_kind'] == 'heuristic' or rule['calibration'] != 'explicit'):
            raise ValueError('Uncalibrated thresholds cannot enter model feedback')
        if rule['source_kind'] == 'instruction':
            quote = rule.get('source_quote')
            if not quote or (instruction is not None and quote not in instruction):
                raise ValueError('Requirement quote must occur in the instruction')
    manual = raw.get('manual_requirements', [])
    names = [item.get('id') for item in manual]
    if len(set(names)) != len(names) or any(not isinstance(n, str) or not n for n in names):
        raise ValueError('Invalid manual requirement identifiers')
    for item in manual:
        if not item.get('question') or not item.get('evidence_needed'):
            raise ValueError('Manual review must explain what evidence is needed')
    if not isinstance(raw.get('visual_regions', []), list):
        raise ValueError('visual_regions must be a list')
    reviewed = any(r['calibration'] == 'reviewed' for r in raw['checks'].values())
    if reviewed or raw.get('calibration_record'):
        record = raw.get('calibration_record', {})
        if not record.get('baseline_requirements') or not record.get('response'):
            raise ValueError('Reviewed calibration needs its bound evidence record')
        expected = apply_calibration(record['baseline_requirements'], record['response'])
        if raw != expected:
            raise ValueError('Reviewed requirements differ from accepted calibration')
    return raw


def coverage(requirements, report):
    checks = {c['id']: c for module in report['modules'].values() for c in module['checks']}
    calibration = [name for name, rule in requirements['checks'].items()
                   if rule['calibration'] == 'pending_human']
    manual = [item['id'] for item in requirements['manual_requirements']]
    return {'requirements_sha256': digest(requirements),
            'automatic_case_pass': report['case_pass'],
            'automatic_checks': {name: {'passed': checks[name]['passed'],
                'status': checks[name]['status'], 'source_kind': rule['source_kind'],
                'calibration': rule['calibration']} for name, rule in requirements['checks'].items()},
            'pending_calibration': calibration, 'pending_manual_review': manual,
            'task_completion': 'pending_human' if calibration or manual else
                ('passed' if report['case_pass'] else 'failed'),
            'calibrated_automatic_score_eligible': not calibration,
            'formal_score_eligible': not calibration and not manual,
            'note': 'S_core/case_pass are automatic-rule results; pending evidence is never a human approval.'}


def calibration_template(requirements):
    return {'requirements_sha256': digest(requirements), 'reviewer': '', 'reviewed_at': '',
            'decisions': {name: {'decision': 'pending', 'rationale': '', 'samples': []}
                for name, rule in requirements['checks'].items() if rule['calibration'] == 'pending_human'}}


def validate_calibration(value, requirements):
    expected = calibration_template(requirements)
    if value.get('requirements_sha256') != expected['requirements_sha256'] or set(value.get('decisions', {})) != set(expected['decisions']):
        raise ValueError('Calibration must bind and cover all pending thresholds')
    pending, rejected = [], []
    for name, decision in value['decisions'].items():
        status = decision.get('decision')
        if status not in {'pending', 'accept', 'revise'}:
            raise ValueError('Invalid calibration decision')
        if status == 'pending':
            pending.append(name)
            continue
        if not value.get('reviewer', '').strip() or not value.get('reviewed_at', '').strip() or not decision.get('rationale', '').strip():
            raise ValueError('Calibration requires a reviewer, date and rationale')
        samples = decision.get('samples', [])
        if status == 'accept':
            labels = {s.get('expected_pass') for s in samples}
            if labels != {True, False} or any(type(s.get('expected_pass')) is not bool
                    or type(s.get('observed_pass')) is not bool or s['expected_pass'] != s['observed_pass']
                    or not s.get('evidence_path') or len(s.get('evidence_sha256', '')) != 64 for s in samples):
                raise ValueError('Accepted calibration needs matching positive and negative evidence samples')
            for sample in samples:
                path = Path(sample['evidence_path'])
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sample['evidence_sha256']:
                    raise ValueError('Calibration evidence missing or changed')
                report = json.loads(path.read_text())
                measured = {c['id']: c for m in report.get('modules', {}).values() for c in m.get('checks', [])}
                if (report.get('spec_sha256') != requirements['spec_sha256'] or report.get('task_id') != requirements['task_id']
                        or measured.get(name, {}).get('passed') is not sample['observed_pass']):
                    raise ValueError('Calibration observation does not match the bound task report')
        else:
            rejected.append(name)
    return {'status': 'revise_required' if rejected else 'pending_human' if pending else 'accepted',
            'pending': pending, 'revise': rejected}


def apply_calibration(requirements, response):
    """Publish a separate reviewed profile; never mutate an existing experiment."""
    import copy
    if requirements.get('calibration_record'):
        raise ValueError('Calibration is already attached; revise the specification for another calibration cycle')
    result = validate_calibration(response, requirements)
    if result['status'] != 'accepted':
        raise ValueError('Only a fully accepted calibration can produce a reviewed profile')
    revised = copy.deepcopy(requirements)
    for name in response['decisions']:
        revised['checks'][name]['calibration'] = 'reviewed'
    revised['calibration_record'] = {'baseline_requirements': requirements, 'response': response}
    return revised
