"""Case-specific section checks and source-bound worker/metric integration."""
import copy
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pytest
import shapely

from src.evaluator.l1_compute import run_compute
from src.evaluator.l1_failures import InspectionFailure
from src.evaluator.l1_seed_quality import selected_checks
from src.evaluator.l1_surface import SurfaceMesh
from src.evaluator.l1_sweep import REFERENCE_PROTOCOL, reference_mesh
from src.evaluator.l1_sweep_measurements import (
    PROTOCOL,
    inspect_sweep,
    measure_sections,
    rectangular_verdict,
    self_intersection_witness,
    validate_design,
)
from src.evaluator.metrics import MissingEvidence, swept_bar, validate_metrics
from src.evaluator.spec import EvalSpec
from tools.activate_l1_sweep import expand

ROOT=Path(__file__).resolve().parents[1]
CASE=ROOT/'data/3dbench/tasks/L1/Text2Code/task_L1_Text2Code_014'


def test_self_intersection_zero_requires_a_proper_crossing_outside_numeric_guard():
    assert self_intersection_witness([[0, 0], [.01, .01], [0, .01], [.01, 0]])
    assert self_intersection_witness([[0, 0], [.01, 0], [.01, .01], [0, .01]]) is None
    # Nearly coincident corners are insufficient evidence of a CAD defect.
    assert self_intersection_witness([[0, 0], [.01, .01], [0, .01], [1e-12, 0]]) is None


def test_nonrectangular_boundary_has_a_measured_rejection_witness():
    # All extrema match the rectangle, but the actual top edge contains a dent.
    boundary = shapely.Polygon([(0, 0), (.01, 0), (.01, .01),
                               (.005, .006), (0, .01)]).boundary
    result = rectangular_verdict({'status': 'measured', 'boundary': boundary,
        'rectangle': shapely.box(0, 0, .01, .01).boundary}, .00015)
    assert result['status'] == 'failed' and result['passed'] is False
    assert result['failure_type'] == 'candidate_content'
    assert result['witness']['distance_m'] > result['tolerance_m'] + result['guard_m']
    point = shapely.Point(result['witness']['point_m'])
    target = shapely.box(0, 0, .01, .01).boundary
    assert point.distance(target) == pytest.approx(result['witness']['distance_m'])


def test_failed_sufficient_boundary_proof_alone_does_not_assign_zero(monkeypatch):
    import src.evaluator.l1_sweep_measurements as module
    monkeypatch.setattr(module, 'rectangular_bound', lambda *args: False)
    boundary = shapely.box(0, 0, .01, .01).boundary
    result = rectangular_verdict({'status': 'measured', 'boundary': boundary,
                                  'rectangle': boundary}, .00015)
    assert result['status'] == 'not_measurable'
    assert 'policy' not in result


def reference():
    return {'protocol':REFERENCE_PROTOCOL,'units':'metres','depth_m':.0069,'width_m':.0093,
        'surface_tolerance_m':.00015,
        'strips_xz_m': [[[[-.00465,0],[-.00465,.02]],[[.00465,0],[.00465,.02]]]]}


def prepared(tmp_path):
    path=tmp_path/'harness/reference.json'
    path.parent.mkdir()
    path.write_text(json.dumps(reference()))
    design={'width_m':.0093,'depth_m':.0069,'tolerance_m':.00015,
        'reference_path':'harness/reference.json','reference_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    mesh,_=reference_mesh(reference(),error_m=1e-5)
    payload=tmp_path/'actual.npz'
    np.savez_compressed(payload,vertices_m=mesh.vertices,triangles=mesh.triangles)
    record={'coordinate_space':'world_metres','path':str(payload),'sha256':hashlib.sha256(payload.read_bytes()).hexdigest()}
    scene={'objects':{'arbitrary_name':{'type':'MESH','entity_scope':'delivery_geometry','valid_solid':True,
        'closed':True,'components':1,'editable':True,'mesh_payload':record}}}
    return scene,design


@pytest.mark.parametrize('axis,delta',[(0,.0001),(1,.0001),(0,.0002),(1,.0002)])
def test_independent_full_dimension_not_per_side_surface_error(axis,delta):
    ref=reference()
    mesh,_=reference_mesh(ref,error_m=1e-5)
    v=mesh.vertices.copy()
    width=ref['width_m'] if axis==0 else ref['depth_m']
    v[:,axis]*=(width+delta)/width
    result=measure_sections(SurfaceMesh(v,mesh.triangles),ref,{'width_m':.0093,'depth_m':.0069,'tolerance_m':.00015})
    assert result['status']==('passed' if delta<.00015 else 'failed')
    assert not result['omitted'] and len(result['sections'])==5


def test_real_reference_selection_is_not_candidate_controlled():
    ref=json.loads((CASE/'harness/sweep_reference/reference_v1.json').read_text())
    data=json.loads((ROOT/'tests/fixtures/l1_cases/text014/assets/public_sweep.json').read_text())
    mesh=SurfaceMesh(data['vertices'],np.asarray(data['faces']))
    design={'width_m':.0093,'depth_m':.0069,'tolerance_m':.00015}
    normal=measure_sections(mesh,ref,design)
    wrong=SurfaceMesh(mesh.vertices*[1,1.1,1],mesh.triangles)
    failed=measure_sections(wrong,ref,design)
    assert normal['status']=='passed' and len(normal['sections'])==25
    assert len(normal['omitted'])==5 and {r['span'] for r in normal['omitted']}=={4}
    assert failed['status']=='failed' and failed['omitted']==normal['omitted']


def test_actual_worker_and_mesh_binding(tmp_path):
    scene,design=prepared(tmp_path)
    result=run_compute('swept_bar',{'scene':scene,'design':design,'trusted_root':str(tmp_path),
        'assets_root':str(tmp_path)},output=tmp_path/'compute',deadline=time.monotonic()+20)
    assert result['protocol']==PROTOCOL and result['passed']
    assert result['source']['mesh_payload']==scene['objects']['arbitrary_name']['mesh_payload']
    assert result['compute_execution']['cleanup_ack'] and result['compute_execution']['leader_reaped']


def test_expired_job_cannot_pass(tmp_path):
    scene,design=prepared(tmp_path)
    with pytest.raises(InspectionFailure):
        run_compute('swept_bar',{'scene':scene,'design':design,'trusted_root':str(tmp_path),
            'assets_root':str(tmp_path)},output=tmp_path/'compute',deadline=time.monotonic()-.1)


def test_reference_hash_mismatch_rejected(tmp_path):
    scene,design=prepared(tmp_path)
    design['reference_sha256']='0'*64
    with pytest.raises(ValueError,match='hash mismatch'):
        inspect_sweep(scene,design,trusted_root=tmp_path,assets_root=tmp_path)


@pytest.mark.parametrize('field,value',[('depth_m',True),('width_m',float('nan')),('reference_sha256',True),
    ('reference_path','../outside.json'),('reference_path','input/answer.json'),('tolerance_m',.01)])
def test_invalid_design(tmp_path,field,value):
    _,design=prepared(tmp_path)
    design[field]=value
    with pytest.raises(ValueError):
        validate_design(design)


def spec():
    return expand(json.loads((CASE/'harness/eval_spec.json').read_text()),'1'*64)


def test_activation_idempotent_all_seed_and_not_l2():
    before=spec()
    assert expand(before,'1'*64)==before
    parsed=EvalSpec.from_dict(before)
    validate_metrics(parsed)
    selected=selected_checks(parsed)
    assert len([c for c in selected.values() if c.metric=='swept_bar'])==6
    assert {c.id for c in selected.values()}==set(next(c for g in parsed.checks.values() for c in g
        if c.metric=='all_seed_checks').params['checks'])
    before['profile']='L2'
    with pytest.raises(ValueError):
        validate_metrics(EvalSpec.from_dict(before))


def test_shared_cache_cannot_alias_native_and_glb():
    raw=spec()
    definitions=[c for c in raw['checks']['geometry'] if c['metric']=='swept_bar']
    definitions[-1]['params']['path']=definitions[0]['params']['path']
    with pytest.raises(ValueError,match='Conflicting'):
        validate_metrics(EvalSpec.from_dict(raw))


def test_metric_binds_actual_scene_reference_and_unavailable(tmp_path):
    scene,design=prepared(tmp_path)
    audit=inspect_sweep(scene,design,trusted_root=tmp_path,assets_root=tmp_path)
    raw=spec()
    for check in raw['checks']['geometry']:
        if check['metric']=='swept_bar':check['params']['design']=design
    parsed=EvalSpec.from_dict(raw)
    check=next(c for c in parsed.checks['geometry'] if c.id=='native_sweep_surface')
    evidence={'scene':scene,'numeric_checks':{'native_sweep':audit}}
    assert swept_bar(check,evidence,parsed)[0]==1
    changed=copy.deepcopy(evidence)
    changed['scene']['objects']['arbitrary_name']['mesh_payload']['sha256']='f'*64
    with pytest.raises(MissingEvidence):swept_bar(check,changed,parsed)
    changed=copy.deepcopy(evidence)
    changed['numeric_checks']['native_sweep']['features']['surface']={'status':'not_measurable','passed':False}
    with pytest.raises(MissingEvidence):swept_bar(check,changed,parsed)
