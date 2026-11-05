import pytest
from src.evaluator.content_evidence_policy import codeedit_partial,seed_system_status,l2_audit_valid,rerender_available


def report():
    good={'passed':True,'measurement_status':'passed'}
    bad={'passed':False,'measurement_status':'failed'}
    seed={'prerequisites':{'execution':good},'system_checks':{'material':good,'reproducible':bad}}
    return {'gates':{'execution':good,'integrity':good,
        'reproducible':{**bad,'details':{'per_seed':{'0':{'execution_passed':True}}}},
        'all_seeds':{**bad,'details':{'per_seed':{'0':seed}}}},
        'score_components':{'numeric':1.,'target':.1,'preservation':.8},'components':{}}


def test_geometry_mismatch_keeps_existing_partial_components():
    r=report();q=codeedit_partial(r)
    assert q['S_core']==pytest.approx(.6) and q['score_valid']
    assert r['gates']['reproducible']['passed'] is False
    assert q['quality_diagnostics']['reproduction_equality']['passed'] is False


def test_geometry_policy_preserves_material_failure_and_execution_requirement():
    r=report();r['gates']['all_seeds']['details']['per_seed']['0']['system_checks']['material']={'passed':False,'measurement_status':'failed'}
    assert codeedit_partial(r)['S_core']==0.
    r=report();r['gates']['reproducible']['details']['per_seed']['0']['execution_passed']=False
    with pytest.raises(ValueError,match='executions'):codeedit_partial(r)


def test_saved_pixel_mismatch_can_use_successful_rerender_but_not_failed_audit():
    replay={'status':'measured','passed':False,'views':{'main.png':{'render_path':'/bound.png'}}}
    row={'execution_passed':True,'audit':{'passed':True},'rerender':replay,'reproduction_matches_baseline':False}
    assert l2_audit_valid(row)
    row['audit']['passed']=False
    assert not l2_audit_valid(row)
    assert not rerender_available({'status':'not_measurable','views':{}})


def test_missing_seed_system_evidence_is_not_assumed_passed():
    assert seed_system_status({})=='not_measurable'


def test_native_raster_mistake_has_zero_image_credit_without_resizing(tmp_path):
    from PIL import Image
    from tools.evaluate_linear_candidate import pin
    from src.evaluator.l2_method_scoring import compare_main_image
    from src.evaluator.content_evidence_policy import VERSION
    a=tmp_path/'reference.png';b=tmp_path/'native.png'
    Image.new('RGB',(8,6),'white').save(a);Image.new('RGB',(8,12),'white').save(b)
    evidence={'artifacts':{'main.png':pin(b)},'reference_images':{'main':pin(a)},'scoring_policy_revision':VERSION}
    r=compare_main_image(evidence)
    assert r['status']=='measured' and r['score']==0.
    assert r['candidate_size']==[8,12]


def test_rerender_requires_hash_bound_image_and_scene(tmp_path):
    from tools.scene_scoring_evidence import replay_images
    from tools.evaluate_linear_candidate import pin
    scene=tmp_path/'scene.blend';scene.write_bytes(b'bound scene')
    image=tmp_path/'main.png';image.write_bytes(b'bound image')
    replay={'status':'measured','passed':False,'views':{
        'main.png':{'render_path':str(image)},'alternate.png':{'render_path':str(image)}}}
    with pytest.raises(ValueError,match='not bound'):
        replay_images(pin(scene),replay,[])
    pointer=pin(image);image.write_bytes(b'changed')
    with pytest.raises(ValueError):replay_images(pin(scene),replay,[pointer])
