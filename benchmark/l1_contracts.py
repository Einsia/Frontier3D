"""Verify native L1 rubric bindings before staging or calling a judge."""
import json
from pathlib import Path

from jsonschema import ValidationError

from orchestrator.tasks import regular, sha256
from src.agent_judge.protocol import contract_hash, validate_spec
from src.evaluator.l1_l2_alignment import BRIEF, digest, validate_plan


def verify_l1_rubrics(root, *, resources=None, allow_stale_instruction_digest=False):
    root = Path(root)
    resources = Path(resources) if resources is not None else root / 'configs/release'
    provenance = json.loads((root / 'configs/release/l1-rubric-bindings.json').read_text())
    records = {row['task_id']: row for row in provenance['tasks']}
    if len(records) != 45 or len(provenance['tasks']) != 45:
        raise ValueError('Expected 45 distinct native L1 rubric bindings')
    plans = sorted((resources / 'l1-plans').rglob('alignment.json'))
    if len(plans) != 45:
        raise ValueError('Expected 45 native L1 alignment plans')
    seen = set()
    updates = []
    for path in plans:
        plan = validate_plan(json.loads(path.read_text()))
        task_id = plan['task_id']
        if task_id in seen or task_id not in records or path.parent.relative_to(resources / 'l1-plans').as_posix() != task_id:
            raise ValueError('Unexpected native L1 plan identity: ' + task_id)
        seen.add(task_id)
        record = records[task_id]
        task = root / 'data/3dbench/tasks' / task_id
        try:
            spec = validate_spec(json.loads(path.with_name('vlm_spec.json').read_text()))
        except ValidationError as error:
            raise ValueError('Invalid L1 rubric schema: ' + task_id) from error
        family = 'Brief2Scene' if plan['profile'] == BRIEF else 'Reference2Scene'
        if spec['case_id'] != task_id or spec['family'] != family:
            raise ValueError('L1 rubric identity mismatch: ' + task_id)
        for name, expected in plan['sources'].items():
            if sha256(regular(task, name)) != expected:
                raise ValueError('L1 alignment source changed: ' + task_id + '/' + name)
        current_instruction = contract_hash((task / 'instruction.md').read_text())
        if spec['instruction_sha256'] != current_instruction or current_instruction != record['released_instruction_sha256']:
            raise ValueError('L1 rubric instruction binding mismatch: ' + task_id)
        current = digest(spec)
        historical = digest({**spec, 'instruction_sha256': record['historical_instruction_sha256']})
        if current != record['released_spec_digest'] or historical != record['historical_spec_digest']:
            raise ValueError('L1 rubric differs beyond the recorded instruction binding: ' + task_id)
        expected = current
        if allow_stale_instruction_digest and plan['vlm_spec_digest'] == record['historical_spec_digest']:
            expected = plan['vlm_spec_digest']
        if plan['vlm_spec_digest'] != expected:
            raise ValueError('Judge rubric differs from the frozen alignment plan: ' + task_id)
        if plan['profile'] != BRIEF:
            if digest(spec.get('localization')) != plan.get('reference_boxes'):
                raise ValueError('Frozen reference box/rubric mismatch: ' + task_id)
            for filename, key in [('reference_boxes.json', 'reference_boxes'), ('reference_regions.json', 'reference_regions')]:
                if digest(json.loads(path.with_name(filename).read_text())) != plan[key]:
                    raise ValueError('L1 reference annotation changed: ' + task_id)
            if plan.get('strict_reference_evidence') and 'cross_view' not in {c['id'] for c in spec['checks']}:
                raise ValueError('Missing required cross_view criterion: ' + task_id)
        mirror = resources / 'linear-config' / task_id / 'alignment.json'
        if plan['profile'] == BRIEF:
            if json.loads(mirror.read_text()) != plan:
                raise ValueError('L1 alignment copies differ: ' + task_id)
        if plan['vlm_spec_digest'] != current:
            updates.append((path, {**plan, 'vlm_spec_digest': current}))
            if plan['profile'] == BRIEF:
                updates.append((mirror, {**plan, 'vlm_spec_digest': current}))
    return updates
