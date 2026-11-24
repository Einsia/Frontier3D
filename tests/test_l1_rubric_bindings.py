"""Exercise every released native L1 plan through the real pre-judge gates."""
import json
from pathlib import Path
import shutil

import pytest

from benchmark.l1_contracts import verify_l1_rubrics
from benchmark.resources import ROOT, prepare
from harness.L1 import l2_aligned_judge
from orchestrator.tasks import sha256, write_json
from src.evaluator.l1_l2_alignment import BRIEF, digest

PLANS = sorted((ROOT / 'configs/release/l1-plans').rglob('alignment.json'))


@pytest.mark.parametrize('plan_path', PLANS, ids=lambda p: p.parent.name)
def test_all_45_native_l1_tasks_reach_judge_runtime(plan_path, tmp_path, monkeypatch):
    plan = json.loads(plan_path.read_text())
    task = ROOT / 'data/3dbench/tasks' / plan['task_id']
    artifacts = {}
    for name in ['main.png', 'alternate.png', 'scene.blend']:
        path = tmp_path / name
        path.write_bytes(b'offline preflight fixture, not rendered candidate evidence')
        artifacts[name] = {'path': str(path), 'sha256': sha256(path)}
    calls = []

    def offline_judge(task_root, evidence, frozen, output, **options):
        calls.append(frozen)
        references = evidence['reference_images']
        if plan.get('strict_reference_evidence'):
            names = [f'reference/reference-{i}' + Path(item['path']).suffix.lower()
                     for i, (_, item) in enumerate(sorted(references.items()))]
            write_json(Path(output) / 'issues.json', {'checks': [
                {'check_id': 'cross_view', 'evidence': [{'file': name} for name in names]}]})
        return {'status': 'scored', 'S_vlm': .5}

    monkeypatch.setattr(l2_aligned_judge, 'judge_task', offline_judge)
    result = l2_aligned_judge.judge_aligned(task, plan, plan_path.with_name('vlm_spec.json'),
                                         {'artifacts': artifacts}, tmp_path / 'judge')
    assert len(calls) == 1
    assert result['vlm_spec_digest'] == plan['vlm_spec_digest']
    assert result['alignment_plan_sha256'] == digest(plan)
    checks = calls[0]['_vlm_judge']['spec']['checks']
    if plan['profile'] != BRIEF:
        assert len(checks) == 10 and 'cross_view' in {c['id'] for c in checks}


@pytest.fixture
def contracts(tmp_path):
    source = ROOT / 'configs/release'
    shutil.copytree(source / 'l1-plans', tmp_path / 'l1-plans')
    shutil.copytree(source / 'linear-config/L1/Text2Code', tmp_path / 'linear-config/L1/Text2Code')
    return tmp_path


def test_rebinding_preserves_rubric_body_and_repairs_only_known_instruction_change(contracts):
    plan_path = contracts / 'l1-plans/L1/Text2Code/task_L1_Text2Code_002/alignment.json'
    mirror = contracts / 'linear-config/L1/Text2Code/task_L1_Text2Code_002/alignment.json'
    before = plan_path.with_name('vlm_spec.json').read_bytes()
    plan = json.loads(plan_path.read_text())
    records = json.loads((ROOT / 'configs/release/l1-rubric-bindings.json').read_text())['tasks']
    historical = next(row for row in records if row['task_id'] == plan['task_id'])
    plan['vlm_spec_digest'] = historical['historical_spec_digest']
    write_json(plan_path, plan)
    write_json(mirror, plan)
    with pytest.raises(ValueError, match='rubric differs from the frozen alignment plan'):
        verify_l1_rubrics(ROOT, resources=contracts)
    updates = verify_l1_rubrics(ROOT, resources=contracts, allow_stale_instruction_digest=True)
    assert {path for path, _ in updates} == {plan_path, mirror}
    for path, value in updates:
        write_json(path, value)
    assert verify_l1_rubrics(ROOT, resources=contracts) == []
    assert verify_l1_rubrics(ROOT, resources=contracts, allow_stale_instruction_digest=True) == []
    assert plan_path.with_name('vlm_spec.json').read_bytes() == before


def test_rebinding_cannot_accept_changed_judge_text_even_with_new_outer_digest(contracts):
    path = contracts / 'l1-plans/L1/Image2Code/task_L1_Image2Code_001/alignment.json'
    spec_path = path.with_name('vlm_spec.json')
    plan, spec = json.loads(path.read_text()), json.loads(spec_path.read_text())
    spec['focus'] += ' Changed judging guidance.'
    plan['vlm_spec_digest'] = digest(spec)
    write_json(spec_path, spec)
    write_json(path, plan)
    with pytest.raises(ValueError, match='differs beyond the recorded instruction binding'):
        verify_l1_rubrics(ROOT, resources=contracts, allow_stale_instruction_digest=True)


def test_real_judge_still_rejects_rubric_tampering_before_any_call(tmp_path, monkeypatch):
    path = PLANS[0]
    plan = json.loads(path.read_text())
    spec = json.loads(path.with_name('vlm_spec.json').read_text())
    spec['focus'] += ' Unauthorized change.'
    write_json(tmp_path / 'vlm_spec.json', spec)
    monkeypatch.setattr(l2_aligned_judge, 'judge_task', lambda *a, **k: pytest.fail('Unexpected judge call'))
    with pytest.raises(ValueError, match='Judge rubric differs from the frozen alignment plan'):
        l2_aligned_judge.judge_aligned(ROOT / 'data/3dbench/tasks' / plan['task_id'],
                                     plan, tmp_path / 'vlm_spec.json', {}, tmp_path / 'judge')


def test_mismatched_instruction_and_mirrored_plan_fail_preflight(contracts):
    path = contracts / 'l1-plans/L1/Text2Code/task_L1_Text2Code_002/vlm_spec.json'
    original = json.loads(path.read_text())
    write_json(path, {**original, 'instruction_sha256': '0' * 64})
    with pytest.raises(ValueError, match='instruction binding mismatch'):
        verify_l1_rubrics(ROOT, resources=contracts)
    write_json(path, original)
    mirror = contracts / 'linear-config/L1/Text2Code/task_L1_Text2Code_002/alignment.json'
    plan = json.loads(mirror.read_text())
    write_json(mirror, {**plan, 'vlm_spec_digest': '0' * 64})
    with pytest.raises(ValueError, match='alignment copies differ'):
        verify_l1_rubrics(ROOT, resources=contracts)


def test_materialized_contracts_keep_all_45_internal_bindings(tmp_path, monkeypatch):
    monkeypatch.setenv('THREEDBENCH_RESOURCE_ROOT', 'unused')
    root = prepare(tmp_path / 'contracts')
    assert verify_l1_rubrics(ROOT, resources=root) == []
    for path in (root / 'l1-plans').rglob('alignment.json'):
        plan = json.loads(path.read_text())
        assert digest(json.loads(path.with_name('vlm_spec.json').read_text())) == plan['vlm_spec_digest']
