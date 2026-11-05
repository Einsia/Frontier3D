import copy
import math

import pytest

from src.evaluator.l2_reference_boxes import (METHOD, POLICY, PROFILE, checked_box,
    compare_boxes, pair_metrics, add_localization, validate_annotation)


def annotation(boxes=None):
    return {'version':METHOD,'policy':copy.deepcopy(POLICY),'image_size':[1000,500],
        'reference_sha256':'reference','detector':{'fingerprint':'detector'},
        'targets':[{'id':'bed','query':'bed','label':'床','weight':1.,'review_status':'approved',
                    'boxes':boxes or [[.2,.2,.5,.6]]}]}


def detection(boxes):
    return {'status':'measured','image_sha256':'candidate','image_size':[1000,500],
        'detector_fingerprint':'detector','queries':{'bed':[{'box':b,'confidence':.9} for b in boxes]}}


def score(boxes,ref=None):
    return compare_boxes(ref or annotation(),detection(boxes),'candidate')


def test_identity_missing_displaced_and_enlarged():
    assert score([[.2,.2,.5,.6]])['score']==pytest.approx(1.)
    assert score([])['score']==0.
    assert score([[.3,.2,.6,.6]])['score']<.8
    assert score([[.65,.6,.95,1.]])['score']==0.
    assert score([[0,0,1,1]])['score']<.5


def test_one_candidate_cannot_satisfy_two_reference_instances():
    a=annotation([[.1,.2,.3,.5],[.6,.2,.8,.5]])
    result=score([[.1,.2,.3,.5]],a)
    assert result['score']==pytest.approx(.5)
    assert result['targets'][0]['matched_count']==1


def test_duplicate_detector_boxes_suppressed_but_extra_real_instances_penalized():
    b=[.2,.2,.5,.6]
    assert score([b,b,b])['score']==pytest.approx(1.)
    assert score([b,[.7,.7,.95,.95]])['score']==pytest.approx(.5)


def test_confidence_is_a_filter_not_a_grade():
    d=detection([[.2,.2,.5,.6]])
    d['queries']['bed'][0]['confidence']=.3
    assert compare_boxes(annotation(),d,'candidate')['score']==pytest.approx(1.)
    d['queries']['bed'][0]['confidence']=.24
    assert compare_boxes(annotation(),d,'candidate')['score']==0.


@pytest.mark.parametrize('value',[[0,0,0,1],[0,0,1.1,1],[0,0,math.nan,1],[1,0,0,1],[0,0,math.inf,1]])
def test_malformed_boxes_rejected(value):
    with pytest.raises(ValueError):checked_box(value)


@pytest.mark.parametrize('key,value',[('image_sha256','wrong'),('detector_fingerprint','wrong'),('image_size',[500,1000]),('queries',{})])
def test_detection_bound_to_exact_image_detector_queries_and_dimensions(key,value):
    d=detection([]);d[key]=value
    with pytest.raises(ValueError):compare_boxes(annotation(),d,'candidate')


def test_failed_detector_and_unreviewed_reference_are_unknown_not_missing_objects():
    assert compare_boxes(annotation(),{'status':'not_measurable'},'candidate')['score'] is None
    a=annotation();a['targets'][0]['review_status']='pending'
    assert compare_boxes(a,detection([]),'candidate')['score'] is None
    assert score([])['status']=='measured'


def test_semantic_queries_do_not_cross_match():
    a=annotation();a['targets'].append({'id':'chair','label':'椅子','query':'chair','weight':.5,
        'boxes':[[.6,.2,.8,.6]],'review_status':'approved'});a['targets'][0]['weight']=.5
    d=detection([[.6,.2,.8,.6]]);d['queries']['chair']=[{'box':[.2,.2,.5,.6],'confidence':.99}]
    assert compare_boxes(a,d,'candidate')['score']<.2


def test_reflected_bed_is_not_an_additional_physical_instance():
    from src.evaluator.l2_reference_boxes import REFLECTION_PROFILE
    a=annotation();a['scoring_profile']=REFLECTION_PROFILE
    a['targets'][0].update(weight=.5,exclude_reflections_in=['mirror'])
    mirror=[.65,.1,.8,.65]
    a['targets'].append({'id':'mirror','label':'镜子','query':'mirror','weight':.5,
        'boxes':[mirror],'review_status':'approved'})
    reflected=[.66,.4,.78,.6];physical=[.2,.2,.5,.6]
    d=detection([physical,reflected]);d['queries']['mirror']=[{'box':mirror,'confidence':.9}]
    result=compare_boxes(a,d,'candidate')
    assert result['score']==pytest.approx(1.)
    assert result['targets'][0]['candidate_count']==1
    assert result['targets'][0]['ignored_reflections'][0]['box']==reflected
    assert len(d['queries']['bed'])==2  # Raw detector evidence is preserved.
    d['queries']['bed'].append({'box':[.82,.7,.95,.95],'confidence':.9})
    assert compare_boxes(a,d,'candidate')['score']==pytest.approx(.75)
    d['queries']['mirror']=[]
    assert compare_boxes(a,d,'candidate')['targets'][0]['candidate_count']==3
    a['scoring_profile']=PROFILE
    with pytest.raises(ValueError,match='Reflection exclusions'):validate_annotation(a)


def test_real_bed_overlapping_a_mirror_is_not_removed():
    from src.evaluator.l2_reference_boxes import REFLECTION_PROFILE
    a=annotation();a['scoring_profile']=REFLECTION_PROFILE
    a['targets'][0].update(weight=.5,exclude_reflections_in=['mirror'])
    mirror=[.15,.1,.35,.4]
    a['targets'].append({'id':'mirror','label':'镜子','query':'mirror','weight':.5,
        'boxes':[mirror],'review_status':'approved'})
    d=detection([[.2,.2,.5,.6]]);d['queries']['mirror']=[{'box':mirror,'confidence':.9}]
    result=compare_boxes(a,d,'candidate')
    assert result['score']==pytest.approx(1.)
    assert result['targets'][0]['ignored_reflections']==[]


def test_center_distance_accounts_for_image_aspect_ratio():
    a=[.1,.1,.2,.2]
    x=pair_metrics(a,[.2,.1,.3,.2],[1000,500])
    y=pair_metrics(a,[.1,.2,.2,.3],[1000,500])
    assert x['center_distance_diagonal']==pytest.approx(2*y['center_distance_diagonal'])


def base(valid=True):
    return {'method_version':'l2-reference-embodied-v4.0.0','score_valid':valid,'case_pass':valid,
        'status':'passed' if valid else 'failed','score_components':{'main_image':1.,'physics':1.,'render_validity':float(valid)},
        'gates':{'integrity':{'passed':valid}},'protocol':{},'measurements':[],'limitations':[]}


def test_localization_quality_does_not_create_system_gate():
    original=base();r=add_localization(original,score([]))
    assert r['S_core']==pytest.approx(.8) and r['score_valid'] is True
    assert r['gates']==original['gates'] and r['method_version']==PROFILE
    missing=add_localization(original,{'status':'not_measurable','reason':'timeout'})
    assert missing['S_core'] is None and missing['score_valid'] is True
    assert missing['quality_lower_bound']==pytest.approx(.8)
    assert add_localization(base(False),score([[.2,.2,.5,.6]]))['S_core']==0.


def test_valid_reference_weights_required():
    a=annotation();a['targets'][0]['weight']=.5
    with pytest.raises(ValueError):validate_annotation(a)


def test_pending_reference_retains_diagnostic_boxes_without_a_total():
    a=annotation();a['targets'][0].update(review_status='pending',review_note='Ambiguous instance boundary')
    result=compare_boxes(a,detection([[.2,.2,.5,.6]]),'candidate')
    assert result['score'] is None and result['diagnostic_score']==pytest.approx(1.)
    assert result['coverage']==0. and result['targets'][0]['matched_count']==1
    report=add_localization(base(),result)
    assert report['S_core'] is None and report['gates']['integrity']['passed']


def test_reference_annotation_is_bound_to_the_exact_public_image(tmp_path):
    import hashlib,json
    from src.evaluator.l2_reference_boxes import load_annotation
    (tmp_path/'harness').mkdir();(tmp_path/'environment/input').mkdir(parents=True)
    image=tmp_path/'environment/input/reference.png';image.write_bytes(b'fixed reference')
    a=annotation();a.update(reference_path='environment/input/reference.png',
        reference_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    file=tmp_path/'harness/reference_boxes.json';file.write_text(json.dumps(a))
    binding={'path':'harness/reference_boxes.json','sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    assert load_annotation(tmp_path,binding)['targets'][0]['query']=='bed'
    image.write_bytes(b'changed reference')
    with pytest.raises(ValueError,match='Reference image changed'):load_annotation(tmp_path,binding)


def test_refined_profile_is_explicit_and_legacy_keeps_its_version():
    from src.evaluator.l2_reference_boxes import REFINED_PROFILE
    a=annotation();a['scoring_profile']=REFINED_PROFILE
    localized=compare_boxes(a,detection([[.2,.2,.5,.6]]),'candidate')
    assert add_localization(base(),localized)['method_version']==REFINED_PROFILE
    missing=compare_boxes(a,{'status':'not_measurable'},'candidate')
    assert add_localization(base(),missing)['method_version']==REFINED_PROFILE
    assert add_localization(base(),score([]))['method_version']==PROFILE


@pytest.mark.parametrize('contexts',[['bed'],['door','door'],[''],['door',None],'door'])
def test_ambiguous_context_definitions_rejected(contexts):
    a=annotation();a['context_queries']=contexts
    with pytest.raises(ValueError):validate_annotation(a)


def test_realphoto_localization_uses_its_own_base_and_same_quality_weights():
    from src.evaluator.l2_reference_boxes import PHOTO_PROFILE
    a=annotation();a['scoring_profile']=PHOTO_PROFILE
    loc=compare_boxes(a,detection([[.2,.2,.5,.6]]),'candidate')
    original=base();original['method_version']='l2-photo-embodied-v4.0.0'
    result=add_localization(original,loc)
    assert result['S_core']==pytest.approx(1.)
    assert result['method_version']==PHOTO_PROFILE
    assert result['gates']==original['gates']
    with pytest.raises(ValueError):add_localization(base(),loc)
    missing=compare_boxes(a,{'status':'not_measurable'},'candidate')
    assert add_localization(original,missing)['S_core'] is None


def test_unresolved_dark_boundary_is_diagnostic_not_a_model_zero():
    a=annotation();d=detection([[.2,.2,.35,.6]])
    d['boundary_review_required']=[{'reason':'Full limb unresolved'}]
    loc=compare_boxes(a,d,'candidate')
    assert loc['score'] is None and loc['targets'] and loc['diagnostic_score']>0
    report=add_localization(base(),loc)
    assert report['S_core'] is None and report['score_valid']
