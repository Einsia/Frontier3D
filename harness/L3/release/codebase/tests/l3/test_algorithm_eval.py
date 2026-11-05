import numpy as np
import pytest
from PIL import Image

from harness.L3.MinecraftVillage.algorithm_reference import project, crop, mask_boxes, compare
from harness.L3.MinecraftVillage.reference import rendered_mask_color
from harness.L3.MinecraftVillage.algorithm_judge import score_verdict, CHECKLIST
from harness.L3.MinecraftVillage.algorithm_scores import blend
from harness.L3.MinecraftVillage.algorithm_workflow import GridPlanner, door_walk_plan
from harness.L3.MinecraftVillage.protocol import DOORS
from harness.L3.MinecraftVillage.protocol import digest,write_json
from harness.L3.MinecraftVillage.algorithm_geometry import certified_box,unit_cube,union_boxes,compact


def test_camera_projection_targets_center_and_preserves_aspect():
    cam={'position_cm':[1000.,0.,1000.],'look_cm':[0.,0.,0.],'horizontal_fov_deg':60.}
    box=project(np.asarray([[0.,0.,0.]]),cam)
    assert np.allclose(box,[.5,.5,.5,.5])
    assert project(np.asarray([[2000.,0.,2000.]]),cam) is None


def test_mask_measurement_rejects_renderer_fallback(tmp_path):
    p=tmp_path/'mask.png';Image.new('RGB',(16,16),(255,255,255)).save(p)
    with pytest.raises(ValueError,match='palette'):
        mask_boxes(p,[{'id':'a','rgb':[240,40,40]}])


def test_mask_box_uses_visible_pixels_not_claimed_bounds(tmp_path):
    a=np.zeros((20,30,3),np.uint8)
    a[5:10,10:20]=rendered_mask_color([240,40,40],'ue_srgb_linear_display_gamma_2_2')
    p=tmp_path/'mask.png';Image.fromarray(a).save(p)
    rows=mask_boxes(p,[{'id':'a','rgb':[240,40,40]},{'id':'absent','rgb':[40,240,40]}])
    assert len(rows)==1
    assert rows[0]['box']==[10/30,5/20,20/30,10/20]


def test_crop_does_not_stretch_object():
    im=Image.new('RGB',(100,50),'red')
    out=np.asarray(crop(im,[0,0,1,1],100))
    assert np.all(out[:25]==127)
    assert np.all(out[25:75,:]==[255,0,0])


def test_invalid_evidence_never_becomes_zero_or_full_credit():
    v={'checks':{k:{'grade':2,'status':'measured','evidence':['candidate_overview.png']} for k in CHECKLIST}}
    v['checks']['prompt_interiors'].update(grade=None,status='evidence_invalid')
    s=score_verdict(v,['candidate_overview.png'])
    assert s['axes']['prompt_alignment'] is None
    assert s['axes']['beauty']==.5
    v['checks']['prompt_interiors']['grade']=0
    with pytest.raises(ValueError):score_verdict(v,['candidate_overview.png'])


def test_missing_axis_is_not_renormalized():
    s=blend({'a':.8,'b':None},{'a':.75,'b':.25})
    assert s['score'] is None
    assert s['lower_bound']==pytest.approx(.6)
    assert s['upper_bound']==pytest.approx(.85)
    with pytest.raises(ValueError):blend({'a':float('nan')},{'a':1.})


def test_planner_routes_around_wall():
    verts=[[x,y,z] for x in [-10,10] for y in [-100,100] for z in [0,180]]
    scene={'meshes':{'box':{'vertices_cm':verts}},'instances':[{'actor':'wall','mesh':'box','blocks_pawn':True,
        'axis_x':[1,0,0],'axis_y':[0,1,0],'axis_z':[0,0,1],'origin_cm':[0,0,0]}]}
    p=GridPlanner(scene,[[-200,0,85],[200,0,85]],0)
    route=p.route([-200,0,85],[200,0,85])
    assert any(abs(v[1])>100 for v in route)


def test_door_protocol_measures_actual_open_and_closed_movement():
    bindings={'entities':{t:{'approach_cm':[0,0,85],'crossing_from_cm':[0,0,85],'crossing_to_cm':[200,0,85]} for t in DOORS}}
    p,checks=door_walk_plan(bindings)
    assert len(checks)==5
    assert sum(s['op']=='walk_to' for s in p['steps'])==15


def test_reference_identical_and_missing_building_controls(tmp_path):
    im=np.full((90,160,3),[60,120,50],np.uint8)
    im[30:60,60:100]=[150,90,40]
    ref=tmp_path/'ref.png';rgb=tmp_path/'rgb.png';mask=tmp_path/'mask.png';ann=tmp_path/'ann.json'
    Image.fromarray(im).save(ref);Image.fromarray(im).save(rgb)
    pixels=np.zeros_like(im);pixels[30:60,60:100]=rendered_mask_color([240,40,40],'ue_srgb_linear_display_gamma_2_2')
    Image.fromarray(pixels).save(mask)
    write_json(ann,{'status':'test','reference_sha256':digest(ref),'objects':[
        {'id':'r','class':'building','polygon':[[60/160,30/90],[100/160,30/90],[100/160,60/90],[60/160,60/90]]}]})
    groups=[{'id':'candidate','rgb':[240,40,40]}]
    good=compare(ref,rgb,mask,ann,groups,tmp_path/'good')
    assert good['objects_score']==pytest.approx(1.)
    assert good['environment_score']==pytest.approx(1.)
    Image.new('RGB',(160,90),'black').save(mask)
    missing=compare(ref,rgb,mask,ann,groups,tmp_path/'missing')
    assert missing['objects_score']==0
    assert missing['reference_count']==1


def test_box_certificate_rejects_missing_and_duplicate_surfaces():
    cube=unit_cube()
    assert certified_box(cube) is not None
    assert certified_box({**cube,'indices':cube['indices'][:-3]}) is None
    assert certified_box({**cube,'indices':cube['indices']+cube['indices'][:3]}) is None


def test_box_certificate_accepts_subdivided_faces():
    cube=unit_cube();vertices=np.asarray(cube['vertices_cm']);v=[];idx=[]
    for a,b,c in vertices[np.asarray(cube['indices']).reshape(-1,3)]:
        ab=(a+b)/2;bc=(b+c)/2;ca=(c+a)/2
        for triangle in [[a,ab,ca],[ab,b,bc],[ca,bc,c],[ab,bc,ca]]:
            idx.extend(range(len(v),len(v)+3));v.extend(triangle)
    assert certified_box({'vertices_cm':np.asarray(v).tolist(),'indices':idx}) is not None


def test_union_preserves_gap_and_volume():
    a=np.array([[0,0,0],[1,1,1]])
    result=union_boxes([a,a+[1,0,0],a+[3,0,0]])
    assert len(result)==2
    assert sum(np.prod(b[1]-b[0]) for b in result)==3


def test_dynamic_contract_entities_are_not_merged():
    items=[{'actor':'house01.door','component':'leaf','instance':i,'mesh':'cube',
            'axis_x':[1,0,0],'axis_y':[0,1,0],'axis_z':[0,0,1],'origin_cm':[i,0,0],'blocks_pawn':True} for i in range(2)]
    out,proof=compact({'meshes':{'cube':unit_cube()},'instances':items})
    assert len(out['instances'])==2
    assert not proof['dynamic_entities_merged']
    assert all(i['component']=='leaf' for i in out['instances'])


def test_rigid_coverage_excludes_only_known_engine_drawing_helpers():
    from harness.L3.MinecraftVillage.algorithm_scores import rigid_coverage
    raw={'measurement_complete':False,'unresolved_pair_count':0,'unexported_components':[
        {'class':'GameplayDebuggerRenderingComponent'},{'class':'TextRenderComponent'}]}
    assert rigid_coverage(raw)['exported_solids_complete']
    assert len(rigid_coverage(raw)['non_solid_renderers'])==2
    assert not rigid_coverage({**raw,'unresolved_pair_count':1})['exported_solids_complete']
    assert not rigid_coverage({**raw,'unexported_components':[{'class':'ProceduralMeshComponent'}]})['exported_solids_complete']
