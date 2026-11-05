import copy
import json

import pytest

from src.evaluator.l1_candidate_content import POLICY
from src.evaluator.l1_l2_alignment import aggregate, digest, make_plan, measure_data, SYSTEM_GATES
from src.evaluator.l1_requirements import check_outcome
from src.evaluator.metrics import evaluate_metric
from src.evaluator.spec import CheckSpec, EvalSpec, L1_WEIGHTS
from src.agent_judge import l2_rubric


def fixture():
    hole = dict(id='holes', metric='hole_pattern', group='holes', params=dict(
        centers=[[0., 0.]], z_values=[.001, .003], radius=.0032,
        tolerance=.0001, object_dimensions=[.1, .1, .008],
        object_dimension_tolerance=.0001))
    raw = dict(profile='L1', mode='text', required_artifacts=['scene.blend'], checks={
        key: [dict(id=key, group=key, metric='equals', params=dict(path='/ok', expected=True))]
        for key in L1_WEIGHTS})
    raw['checks']['geometry'] = [hole]
    raw['l1_protocol'] = dict(version='l1-requirements-v1', requirements=[dict(
        id='feature', text='A body and its holes', source='instruction.md', required=True,
        applicable=True, implementation='complete', check_ids=['holes'], reason='')])
    evidence = dict(ok=True, inspector_execution=dict(status='completed'), probes={'holes': None},
        scene=dict(coordinate_units='metres', unit_scale=.001, unsupported_geometry=[],
            has_instances=False, mesh_count=1, object_count=1, objects={'plate': dict(
                type='MESH', visible_render=True, dimensions=[.0001, .0001, .000008])}))
    return EvalSpec.from_dict(raw), CheckSpec.parse(hole), evidence


def test_wrong_dimensions_zero_only_the_affected_check_and_retain_partial_credit():
    spec, hole, evidence = fixture()
    result = evaluate_metric(hole, evidence, spec)
    assert result.status == 'ok' and result.score == 0 and result.passed is False
    row = dict(id=hole.id, **result.to_dict())
    row['measurement_status'] = check_outcome(row, evidence)
    assert row['measurement_status'] == 'failed'
    assert result.details['policy'] == POLICY
    good = spec.checks['spec'][0]
    positive = evaluate_metric(good, evidence, spec)
    assert positive.score == 1 and positive.passed
    task = 'L1/Text2Code/task_L1_Text2Code_999'
    plan = make_plan(dict(id=task, title='test', category='Text2Code'), spec, {}, ['holes', 'spec'])
    data = measure_data(plan, {'holes': row, 'spec': dict(score=1., measurement_status='passed')})
    assert data['status'] == 'measured' and data['score'] == .5
    plan['physics'].update(review_status='approved', policy={'fixture': True})
    plan['vlm_spec_digest'] = 'rubric'
    artifact = {'scene.blend': 'scene', 'main.png': 'image'}
    judgment = dict(status='scored', protocol=l2_rubric.PROTOCOL, case_id=task, S_vlm=.9,
        image_sha256='image', vlm_spec_digest='rubric', alignment_plan_sha256=digest(plan))
    report = aggregate(plan,
        {key: dict(measurement_status='passed', passed=True) for key in SYSTEM_GATES},
        dict(data=data, physics=dict(method='l1-assembly-support-v1', status='measured', score=.8,
            context_sha256=digest(plan['physics']), scene_sha256='scene')),
        judgment, artifact_sha256=artifact)
    assert report['S_core'] == pytest.approx(.77)
    assert report['score_components']['vlm'] == .9
    assert report['score_components']['physics'] == .8


@pytest.mark.parametrize('fault', ['no_inspection', 'timeout', 'no_probe', 'unsupported',
    'instances', 'incomplete_census', 'missing_dimensions', 'measurement_failure', 'matching_body'])
def test_missing_or_ambiguous_measurement_is_not_converted_to_content_zero(fault):
    spec, hole, evidence = fixture()
    if fault == 'no_inspection': evidence.pop('inspector_execution')
    if fault == 'timeout': evidence['inspector_execution']['status'] = 'timeout'
    if fault == 'no_probe': evidence['probes'].clear()
    if fault == 'unsupported': evidence['scene']['unsupported_geometry'] = ['CURVE']
    if fault == 'instances': evidence['scene']['has_instances'] = True
    if fault == 'incomplete_census': evidence['scene']['mesh_count'] = 2
    if fault == 'missing_dimensions': evidence['scene']['objects']['plate'].pop('dimensions')
    if fault == 'measurement_failure': evidence['measurement_failures'] = {'holes': {'status': 'infrastructure_error'}}
    if fault == 'matching_body': evidence['scene']['objects']['plate']['dimensions'] = [.1, .1, .008]
    result = evaluate_metric(hole, evidence, spec)
    assert result.status == 'missing'
    assert 'policy' not in result.details


def test_a_measured_hole_retains_its_actual_score():
    spec, hole, evidence = fixture()
    evidence['probes']['holes'] = dict(holes=[dict(max_radius_error=0., through_axis=True, layers=[])])
    result = evaluate_metric(hole, evidence, spec)
    assert result.score == 1 and result.passed
    assert 'policy' not in result.details


def retained_case(tmp_path, monkeypatch):
    from tools import run_l1_strict_review
    from orchestrator.tasks import sha256
    monkeypatch.setattr(run_l1_strict_review, 'ROOT', tmp_path)
    spec, hole, evidence = fixture()
    task = 'L1/Text2Code/task_L1_Text2Code_999'
    campaign = tmp_path/'data/3dbench_merge_test/agent-run/output/model/max'
    job = campaign/'jobs/task_L1_Text2Code_999'
    run = job/'native/selected'
    source = job/'generation/source/solution.py'
    source.parent.mkdir(parents=True)
    source.write_text('original generated code')
    scene = run/'submission/scene.blend'
    scene.parent.mkdir(parents=True)
    scene.write_bytes(b'original scene')
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    sources = {'solution.py': sha256(source)}
    evidence['artifacts'] = {'scene.blend': {'sha256': sha256(scene), 'hash_io': {'path': str(scene)}}}
    ep = run/'evidence.json'
    write(ep, evidence)
    write(run/'run.json', dict(task_id=task, source_sha256=sources, evidence_path=str(ep)))
    write(run/'configuration/eval_spec.json', spec.to_dict())
    write(job/'generate-result.json', dict(source_sha256=sources, submission=str(source.parent)))
    write(job/'native-result.json', dict(run_dir=str(run)))
    plan = make_plan(dict(id=task, title='test', category='Text2Code'), spec, {}, ['holes', 'spec'])
    plan['physics'].update(review_status='approved', policy={'fixture': True})
    plan['vlm_spec_digest'] = 'rubric'
    row = dict(id=hole.id, metric=hole.metric, params=hole.params, score=0., passed=False,
        status='missing', measurement_status='not_measurable', details={'error': 'old missing probe'})
    data = measure_data(plan, {'holes': row, 'spec': dict(score=1., measurement_status='passed')})
    judgment = dict(status='scored', protocol=l2_rubric.PROTOCOL, case_id=task, S_vlm=.9,
        image_sha256='image', vlm_spec_digest='rubric', alignment_plan_sha256=digest(plan))
    report = aggregate(plan,
        {key: dict(measurement_status='passed', passed=True) for key in SYSTEM_GATES},
        dict(data=data, physics=dict(method='l1-assembly-support-v1', status='measured', score=.8,
            context_sha256=digest(plan['physics']), scene_sha256=sha256(scene))), judgment,
        artifact_sha256={'scene.blend': sha256(scene), 'main.png': 'image'})
    report.update(model='model', source_run_dir=str(run), source_bindings={})
    path = campaign/'legacy_baseline/model/cases/task_L1_Text2Code_999/report.json'
    write(path, report)
    write(campaign/'legacy_baseline/plans'/task/'alignment.json', plan)
    return path, ep, job


def test_replay_retains_original_and_positive_scores_and_rejects_unrelated_edits(tmp_path, monkeypatch):
    from tools.recover_candidate_content_partial import recover, verify_recovery
    from tools.recover_l1_strict_axes import verified_baseline_path
    path, _, _ = retained_case(tmp_path, monkeypatch)
    original_bytes = path.read_bytes()
    result = recover(path)
    assert result['S_core'] == pytest.approx(.77)
    assert result['candidate_content_recovery']['replaced_checks'] == ['holes']
    assert path.read_bytes() == original_bytes
    assert result['score_components']['physics'] == .8
    assert result['score_components']['vlm'] == .9
    assert verified_baseline_path(path) == path.with_name('candidate_partial_report.json')
    bad = copy.deepcopy(result)
    bad['measurements']['physics']['score'] = 0
    with pytest.raises(ValueError, match='unrelated evidence or arithmetic'):
        verify_recovery(bad)


def test_replay_keeps_inspection_failure_unresolved(tmp_path, monkeypatch):
    from tools.recover_candidate_content_partial import recover
    path, ep, _ = retained_case(tmp_path, monkeypatch)
    evidence = json.loads(ep.read_text())
    evidence['inspector_execution']['status'] = 'timeout'
    ep.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='No confirmed candidate-content'):
        recover(path)
    assert not path.with_name('candidate_partial_report.json').exists()


def test_automatic_partial_fallback_keeps_unknown_faults_and_surfaces_binding_errors(tmp_path, monkeypatch):
    from tools.recover_candidate_content_partial import recover_if_confirmed
    path, ep, job = retained_case(tmp_path, monkeypatch)
    evidence = json.loads(ep.read_text())
    evidence['inspector_execution']['status'] = 'timeout'
    ep.write_text(json.dumps(evidence))
    assert recover_if_confirmed(path) is None
    (job/'native-result.json').write_text(json.dumps({'run_dir': str(job/'native/another')}))
    with pytest.raises(ValueError, match='currently selected candidate'):
        recover_if_confirmed(path)


def test_replay_rejects_a_baseline_of_another_native_execution(tmp_path, monkeypatch):
    from tools.recover_candidate_content_partial import recover
    path, _, job = retained_case(tmp_path, monkeypatch)
    (job/'native-result.json').write_text(json.dumps({'run_dir': str(job/'native/another')}))
    with pytest.raises(ValueError, match='currently selected candidate'):
        recover(path)
