import copy
from pathlib import Path

import numpy as np
import pytest

from src.evaluator.l1_edit_quality import apply, components, PROFILE
from src.evaluator.l1_edit_surface import compare
from src.evaluator.l1_surface import SurfaceMesh
from src.evaluator.spec import EvalSpec
from src.evaluator.metrics import validate_metrics

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/edit-quality-policy.json'


def fixture():
    spec = EvalSpec.load(FIXTURE)
    policy = spec.to_dict()['l1_edit_quality']
    modules = {name:{'checks':[{'id':c.id,'metric':c.metric,'params':c.params,'details':{},
                 'measurement_status':'passed','score':1.,'passed':True} for c in checks]}
               for name,checks in spec.checks.items()}
    rows = {c['id']:c for module in modules.values() for c in module['checks']}
    seed = next(c for c in rows.values() if c['metric']=='all_seed_checks')
    seed['details']={'per_seed':{str(s):{'status':'passed','failed_prerequisites':[],
                                      'prerequisites':{'execution':{'passed':True,'measurement_status':'passed'}},
                                      'system_checks':{'reproducible':{'passed':True,'measurement_status':'passed'}},
                                      'edit_components':{'numeric':1.,'target':1.,'preservation':1.}} for s in spec.seeds}}
    report={'modules':modules,'gates':{n:{'passed':True,'measurement_status':'passed'} for n in
        ('execution','artifacts','real_geometry','integrity','infrastructure')},
        'task_completion':'incomplete','limitations':[]}
    return spec,policy,rows,report


def test_retained_edit_policy_unit_fixture_validates_separately_from_active_tasks():
    spec=EvalSpec.load(FIXTURE);validate_metrics(spec)
    assert spec.to_dict()['l1_edit_quality']['weights']=={'numeric':.4,'target':.4,'preservation':.2}


def test_numeric_errors_deduct_forty_percent_without_invalidating():
    spec,policy,rows,report=fixture()
    for names in policy['numeric_groups'].values():
        for name in names: rows[name].update(score=0.,passed=False,measurement_status='failed')
    result=apply(report,spec,{})
    assert result['S_core']==pytest.approx(.6) and result['score_valid']
    assert result['method_version']==PROFILE and not result['full_task_verified']
    assert result['quality_score']==pytest.approx(.6)
    assert result['quality_threshold'] is None
    assert result['protocol']['evaluation_mode']=='native_edit_target_quality'
    assert not result['content_requirements']['passed']
    assert result['content_requirements']['affects_eligibility'] is False
    assert result['score_components']['numeric_contribution']==0
    assert sum(result['score_components'][k+'_contribution'] for k in ('numeric','target','preservation'))==pytest.approx(.6)


def test_worst_seed_and_format_cannot_hide_quality_damage():
    spec,policy,rows,report=fixture()
    rows['glb_edit_target'].update(score=.5,passed=False,measurement_status='failed')
    seed=next(c for c in rows.values() if c['metric']=='all_seed_checks')
    seed['details']['per_seed']['2']['edit_components']['numeric']=.25
    result=apply(report,spec,{})
    assert result['S_core']==pytest.approx(.5) and result['score_valid']


@pytest.mark.parametrize('kind',['missing_measurement','missing_seed','infrastructure'])
def test_missing_evidence_is_null_not_an_inflated_or_zero_model_score(kind):
    spec,policy,rows,report=fixture()
    if kind=='missing_measurement':rows[policy['target_checks'][0]]['measurement_status']='not_measurable'
    if kind=='missing_seed':next(c for c in rows.values() if c['metric']=='all_seed_checks')['details']['per_seed'].pop('2')
    if kind=='infrastructure':report['gates']['infrastructure'].update(passed=False,measurement_status='infrastructure_error')
    result=apply(report,spec,{})
    assert result['S_core'] is None and not result['score_valid']
    assert result['score_components']['numeric_contribution'] is None


def test_bitmap_is_still_a_system_failure_and_pending_not_complete():
    spec,policy,rows,report=fixture()
    rows['native_procedural_materials'].update(score=0.,passed=False,measurement_status='failed',
        details=material_audit('BITMAP_NODE'))
    result=apply(report,spec,{})
    assert result['S_core']==0 and not result['score_valid']
    assert result['numeric_requirements']['pending'] and not result['full_task_verified']


def material_audit(code, *, unknown=False):
    return {'protocol':'l1-procedural-materials-v1', 'status':'failed', 'passed':False,
            'material_uses':2, 'violations':[{'owner':'object:Part/slot:0','code':code}],
            'unknown':[{'code':'GRAPH_CYCLE_OR_LIMIT'}] if unknown else []}


def test_unassigned_material_reduces_only_preservation_and_preserves_all_measurements():
    spec,policy,rows,report=fixture()
    rows['native_procedural_materials'].update(score=0.,passed=False,measurement_status='failed',
        details=material_audit('UNASSIGNED_SURFACE'))
    result=apply(report,spec,{})
    assert result['score_valid'] and result['S_core']==pytest.approx(.975)
    assert result['score_components']['numeric']==result['score_components']['target']==1
    assert result['gates']['native_procedural_materials']['passed']
    assert result['material_assignment']['baseline_score']==.5
    assert {m['id'] for m in result['measurements']}==set(rows)|{'material_assignment'}
    material=next(m for m in result['measurements'] if m['id']=='native_procedural_materials')
    assert material['status']=='failed' and material['eligibility_status']=='passed' and not material['affects_quality']
    assert result['content_requirements']['failed']==['material_assignment']


@pytest.mark.parametrize('code,unknown,status',[('UNASSIGNED_SURFACE',True,'not_measurable'),
    ('BITMAP_NODE',True,'system_invalid'),('UNKNOWN_FUTURE_VIOLATION',False,'not_measurable')])
def test_uncertain_audit_is_never_silently_accepted(code,unknown,status):
    spec,policy,rows,report=fixture()
    rows['native_procedural_materials'].update(score=0.,passed=False,measurement_status='failed',
        details=material_audit(code,unknown=unknown))
    result=apply(report,spec,{})
    assert result['status']==status and not result['score_valid']
    assert result['S_core']==(0 if status=='system_invalid' else None)


@pytest.mark.parametrize('semantic,execution,expected',[
        ('ok',True,'passed'),('failed',True,'passed'),('not_measurable',True,'not_measurable'),
    ('not_configured',True,'not_measurable'),(None,True,'not_measurable'),
    ('not_measurable',False,'failed'),('infrastructure_error',True,'infrastructure_error')])
def test_reproduction_keeps_execution_failure_distinct_from_unavailable_geometry(semantic,execution,expected):
    from src.evaluator.l1_edit_validity import reproduction
    from src.evaluator.l1_requirements import check_outcome
    spec,*_=fixture()
    evidence={'harness':{'seed_runs':{str(s):{'passed':True,'reproduction_status':'ok'} for s in spec.seeds}}}
    evidence['harness']['seed_runs']['2']={'passed':execution,'reproduction_status':semantic}
    score,detail=reproduction(spec,evidence)
    assert detail['measurement_status']==expected
    assert score==float(expected=='passed')
    assert detail['outcomes']['2'] is (True if expected=='passed' else False if expected=='failed' else None)
    assert check_outcome({'id':'reproducible','metric':'seed_success','status':'ok',
                          'passed':bool(score),'details':detail},evidence)==expected


def seed_summary_fixture():
    from src.evaluator.spec import EVALUATOR_VERSION
    spec,policy,rows,report=fixture()
    report.update(evaluator_version=EVALUATOR_VERSION,spec_sha256=spec.digest,task_id='fixture',
        artifact_sha256={},scoring_failed=False,budget_exhausted=False,
        compute_execution={'operation':'score','status':'completed','cleanup_ack':True,'leader_reaped':True})
    for group in spec.checks.values():
        for c in group:rows[c.id]['pass_threshold']=c.pass_threshold
    return spec,policy,rows,report


def test_seed_missing_content_retains_numeric_and_target_without_becoming_system_failure():
    from src.evaluator.l1_seed_quality import seed_report_summary
    spec,policy,rows,report=seed_summary_fixture()
    missing=policy['preservation_groups']['preserved_bottom'][0]
    rows[missing].update(measurement_status='not_measurable',score=0.,passed=False,details={'error':'unsupported surface'})
    result=seed_report_summary(report,spec,{},task_id='fixture')
    assert result['status']=='passed'
    assert result['edit_components']=={'numeric':1.,'target':1.,'preservation':None}
    assert result['unverified_checks']==[missing]
    assert result['checks'][missing]['score'] is None


def test_old_seed_report_is_reinterpreted_from_bound_reproduction_input():
    from src.evaluator.l1_seed_quality import seed_report_summary
    spec,policy,rows,report=seed_summary_fixture()
    rows['reproducible'].update(measurement_status='failed',passed=False,score=0.)
    evidence={'harness':{'seed_runs':{str(s):{'passed':True,'reproduction_status':'not_measurable'} for s in spec.seeds}}}
    result=seed_report_summary(report,spec,{},task_id='fixture',evidence=evidence)
    assert result['status']=='not_measurable' and result['checks']['reproducible']['score'] is None
    assert rows['reproducible']['measurement_status']=='failed'  # old report stays unchanged


def test_seed_bitmap_stays_a_failure_when_another_content_check_is_unavailable():
    from src.evaluator.l1_seed_quality import seed_report_summary
    spec,policy,rows,report=seed_summary_fixture()
    rows['native_procedural_materials'].update(score=0.,passed=False,measurement_status='failed',details=material_audit('BITMAP_NODE'))
    rows['native_edit_target'].update(score=0.,passed=False,measurement_status='not_measurable')
    result=seed_report_summary(report,spec,{},task_id='fixture')
    assert result['status']=='failed' and result['edit_components']['target'] is None


def test_duplicate_or_changed_weights_rejected():
    spec,policy,rows,report=fixture()
    raw=spec.to_dict();raw['l1_edit_quality']['weights']['numeric']=.5
    with pytest.raises(ValueError):EvalSpec.from_dict(raw)
    raw=spec.to_dict();raw['l1_edit_quality']['numeric_groups']['duplicate']=['native_edit_target']
    with pytest.raises(ValueError):EvalSpec.from_dict(raw)


def planes(z=0.,extra=False,protected_shift=0.):
    vertices=np.array([[0,0,protected_shift],[1,0,protected_shift],[1,1,protected_shift],[0,1,protected_shift],
                       [2,0,z],[3,0,z],[3,1,z],[2,1,z]])
    triangles=np.array([[0,1,2],[0,2,3],[4,5,6],[4,6,7]])
    if extra:
        vertices=np.concatenate([vertices,[[5,0,0],[6,0,0],[6,1,0],[5,1,0]]])
        triangles=np.concatenate([triangles,[[8,9,10],[8,10,11]]])
    return SurfaceMesh(vertices,triangles)


def test_target_edit_not_entire_unchanged_scene_and_no_pose_alignment():
    baseline=planes();reference=planes(z=.2)
    args=dict(dimension_m=.01,preserve_m=.005,samples=512)
    correct=compare(reference,baseline,reference,**args)
    unchanged=compare(baseline,baseline,reference,**args)
    damaged=compare(planes(z=.2,protected_shift=.1),baseline,reference,**args)
    extra=compare(planes(z=.2,extra=True),baseline,reference,**args)
    assert correct['target']==1 and correct['preservation']==1
    assert unchanged['target']==0 and unchanged['preservation']==1
    assert damaged['preservation']<.01
    assert extra['target']<correct['target']


def test_reference_without_a_measurable_edit_does_not_default_to_perfect():
    result=compare(planes(),planes(),planes(),dimension_m=.01,preserve_m=.005,samples=256)
    assert result['status']=='not_measurable'
