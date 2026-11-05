"""Reference-owned semantic boxes and continuous image-plane location scores.

Only trusted detector output from the evaluator enters this module. A candidate's
object names, bench roles, submitted boxes, or fitted image alignment earn nothing.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

METHOD = 'reference-boxes-v1'
PROFILE = 'l2-reference-localized-v5.0.0'
REFINED_PROFILE = 'l2-reference-localized-v5.1.0'
FULL_EXTENT_PROFILE = 'l2-reference-localized-v5.2.0'
REFLECTION_PROFILE = 'l2-reference-localized-v5.3.0'
PHOTO_PROFILE = 'l2-photo-localized-v5.0.0'
SCENE_PROFILES = {PROFILE,REFINED_PROFILE,FULL_EXTENT_PROFILE,REFLECTION_PROFILE}
PROFILES = {*SCENE_PROFILES,PHOTO_PROFILE}
WEIGHTS = {'main_image': .6, 'localization': .2, 'physics': .1, 'render_validity': .1}
POLICY = {'pair_weights': {'iou': .5, 'center': .3, 'size': .2},
          'center_tolerance_diagonal': .25, 'nms_iou': .5,
          'confidence_threshold': .25, 'max_detections_per_query': 20,
          'extra_detection_penalty': 'reference_count/max(reference_count,candidate_count)'}


def photo_base_plan(plan):
    return {**plan,'scoring':plan['localization_base_scoring']}


def validate_photo_plan(plan):
    from .l2_reference_scoring import validate_visual_plan
    if plan['category'] != 'Reference2Scene-RealPhoto':
        raise ValueError('Photo localization requires the RealPhoto category')
    validate_visual_plan(plan,PHOTO_PROFILE)
    if plan['scoring'].get('main_image_method') != 'native-appearance-v1':
        raise ValueError('Photo localization retains the native whole-image appearance metric')


def checked_box(value):
    box = np.asarray(value, dtype=float)
    if (box.shape != (4,) or not np.isfinite(box).all() or np.any(box < 0)
            or np.any(box > 1) or np.any(box[2:] <= box[:2])):
        raise ValueError('Finite normalized positive xyxy box required')
    return box


def validate_annotation(annotation):
    if annotation.get('scoring_profile',PROFILE) not in PROFILES:
        raise ValueError('Unknown localization scoring profile')
    if annotation.get('version') != METHOD or annotation.get('policy') != POLICY:
        raise ValueError('Version-bound localization policy required')
    targets = annotation.get('targets', [])
    if (not targets or len({t['id'] for t in targets}) != len(targets)
            or len({t['query'] for t in targets}) != len(targets)):
        raise ValueError('Distinct target identifiers and detector queries required')
    if not math.isclose(sum(t['weight'] for t in targets), 1., abs_tol=1e-9):
        raise ValueError('Fixed object weights must sum to one')
    for target in targets:
        if (not isinstance(target['query'], str) or not target['query'].strip()
                or not math.isfinite(target['weight']) or not 0 < target['weight'] <= 1
                or target.get('review_status') not in {'approved', 'pending'}):
            raise ValueError('Invalid target definition or review state')
        if target['review_status'] == 'approved' and not target.get('boxes'):
            raise ValueError('Approved reference target requires actual instance boxes')
        for box in target.get('boxes', []):
            checked_box(box)
        mirrors=target.get('exclude_reflections_in',[])
        if mirrors and (annotation.get('scoring_profile')!=REFLECTION_PROFILE or
                not isinstance(mirrors,list) or any(q not in {t['query'] for t in targets}
                or q==target['query'] for q in mirrors)):
            raise ValueError('Reflection exclusions require v5.3 and distinct frozen reflector queries')
    if not all(isinstance(n, int) and n > 0 for n in annotation.get('image_size', [])) or len(annotation.get('image_size', [])) != 2:
        raise ValueError('Reference image width and height required')
    if not annotation.get('detector', {}).get('fingerprint'):
        raise ValueError('Frozen detector identity required')
    contexts=annotation.get('context_queries',[])
    if (not isinstance(contexts,list) or any(not isinstance(q,str) or not q.strip() for q in contexts)
            or len(set(contexts))!=len(contexts) or set(contexts)&{t['query'] for t in targets}):
        raise ValueError('Distinct object and context phrases required')


def load_annotation(root, binding):
    root = Path(root).resolve()
    if set(binding) != {'path', 'sha256'} or binding['path'] != 'harness/reference_boxes.json':
        raise ValueError('Unexpected object annotation binding')
    file = root/binding['path']
    if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != binding['sha256']:
        raise ValueError('Reference box annotation changed')
    annotation = json.loads(file.read_text())
    validate_annotation(annotation)
    reference = root/annotation['reference_path']
    if not reference.resolve().is_relative_to(root/'environment/input'):
        raise ValueError('Annotated image must be the public task reference')
    if hashlib.sha256(reference.read_bytes()).hexdigest() != annotation['reference_sha256']:
        raise ValueError('Reference image changed after box review')
    return annotation


def pair_metrics(left, right, image_size):
    a, b = checked_box(left), checked_box(right)
    wh_a, wh_b = a[2:]-a[:2], b[2:]-b[:2]
    inter = float(np.prod(np.maximum(0., np.minimum(a[2:], b[2:])-np.maximum(a[:2], b[:2]))))
    iou = inter/(float(np.prod(wh_a)+np.prod(wh_b))-inter)
    pixels = np.asarray(image_size, dtype=float)
    distance = float(np.linalg.norm(((a[:2]+a[2:])-(b[:2]+b[2:]))/2*pixels)/np.linalg.norm(pixels))
    center = max(0., 1.-distance/POLICY['center_tolerance_diagonal'])
    size = float(np.sqrt(np.prod(np.minimum(wh_a, wh_b)/np.maximum(wh_a, wh_b))))
    # A similarly sized object on the opposite side is not a location match.
    score = (.5*iou+.3*center+.2*size) if center > 0 or iou > 0 else 0.
    return {'score': score, 'iou': iou, 'center': center, 'size': size,
            'center_distance_diagonal': distance}


def nms(detections):
    if len(detections) > 900:
        raise ValueError('Detector output exceeds the fixed query capacity')
    ordered = []
    for row in detections:
        checked_box(row['box'])
        score = row['confidence']
        if type(score) not in (float, int) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid detector confidence')
        if score >= POLICY['confidence_threshold']:
            ordered.append(row)
    ordered.sort(key=lambda r: (-r['confidence'], *r['box']))
    kept = []
    for row in ordered:
        if all(pair_metrics(row['box'], other['box'], [1, 1])['iou'] < POLICY['nms_iou'] for other in kept):
            kept.append(row)
        if len(kept) == POLICY['max_detections_per_query']:
            break
    return kept


def compare_boxes(annotation, detection, image_sha256):
    validate_annotation(annotation)
    profile=annotation.get('scoring_profile',PROFILE)
    unavailable = lambda reason: {'method': METHOD, 'scoring_profile':profile,'status': 'not_measurable', 'score': None,
        'reason': reason, 'affects_validity': False, 'targets': [], 'coverage': 0.}
    if detection.get('status') != 'measured':
        return unavailable(detection.get('reason', 'Independent object detection unavailable'))
    if (detection.get('image_sha256') != image_sha256
            or detection.get('detector_fingerprint') != annotation['detector']['fingerprint']
            or detection.get('image_size') != annotation['image_size']):
        raise ValueError('Detection image, dimensions or detector identity changed')
    expected_queries = {t['query'] for t in annotation['targets']}
    if set(detection.get('queries', {})) != expected_queries:
        raise ValueError('Every fixed reference query must have a completed detection result')
    if any(not t.get('boxes') for t in annotation['targets']):
        return unavailable('Reference object boxes await review; weights are not redistributed')
    rows = []
    for target in annotation['targets']:
        candidates = nms(detection['queries'][target['query']])
        ignored=[]
        reflectors=[r for query in target.get('exclude_reflections_in',[]) for r in nms(detection['queries'][query])]
        if reflectors:
            kept=[]
            for candidate in candidates:
                b=checked_box(candidate['box']);area=float(np.prod(b[2:]-b[:2]))
                reflected=next((r for r in reflectors if float(np.prod(np.maximum(0.,
                    np.minimum(b[2:],r['box'][2:])-np.maximum(b[:2],r['box'][:2]))))/area>=.9),None)
                if reflected:
                    ignored.append({**candidate,'reason':'at_least_90_percent_inside_detected_mirror',
                        'reflector_box':reflected['box']})
                else:kept.append(candidate)
            candidates=kept
        boxes = target['boxes']
        pairs = [[pair_metrics(a, b['box'], annotation['image_size']) for b in candidates] for a in boxes]
        matching = {}
        if candidates:
            matrix = np.array([[m['score'] for m in row] for row in pairs])
            left, right = linear_sum_assignment(-matrix)
            matching = {int(i): int(j) for i, j in zip(left, right) if matrix[i, j] > 0}
        instances = []
        for i, box in enumerate(boxes):
            j = matching.get(i)
            metric = pairs[i][j] if j is not None else {'score': 0., 'iou': 0., 'center': 0., 'size': 0., 'center_distance_diagonal': None}
            instances.append({'reference_box': box, 'candidate_box': candidates[j]['box'] if j is not None else None,
                'confidence': candidates[j]['confidence'] if j is not None else None, **metric})
        penalty = len(boxes)/max(len(boxes), len(candidates))
        value = sum(m['score'] for m in instances)/len(boxes)*penalty
        rows.append({'id': target['id'], 'label': target['label'], 'query': target['query'],
            'review_status':target['review_status'],'review_note':target.get('review_note'),
            'weight': target['weight'], 'score': value, 'reference_count': len(boxes),
            'candidate_count': len(candidates), 'matched_count': len(matching),
            'extra_detection_multiplier': penalty, 'instances': instances,
            'ignored_reflections':ignored,
            'unmatched_candidate_boxes': [r['box'] for j, r in enumerate(candidates) if j not in matching.values()]})
    boundary_issues=detection.get('boundary_review_required',[])
    complete=all(t['review_status']=='approved' for t in annotation['targets']) and not boundary_issues
    value=sum(r['weight']*r['score'] for r in rows)
    return {'method': METHOD, 'scoring_profile':profile,'status': 'measured' if complete else 'not_measurable',
        'score':value if complete else None,'diagnostic_score':value,
        'reason':None if complete else 'Full planet boundary unresolved; diagnostic only' if boundary_issues else 'Reference boxes/detector classes await review; diagnostic only, weights are not redistributed',
        'boundary_review_required':boundary_issues,
        'coverage':sum(t['weight'] for t in annotation['targets'] if t['review_status']=='approved'),
        'targets': rows, 'affects_validity': False, 'policy': POLICY,
        'image_size': annotation['image_size'], 'image_sha256': image_sha256,
        'reference_sha256': annotation['reference_sha256'], 'detector_fingerprint': detection['detector_fingerprint'],
        'scope': 'Semantic 2D boxes in the fixed main view; not 3D distance, depth or full semantic correctness',
        'limitations': ['Undetected objects lose location credit; detector mistakes need independent review.',
                        'Frozen queries and boxes; no candidate-dependent reference selection or image alignment.']}


def add_localization(base, localization):
    """Keep historical/system validity and the other measurements unchanged."""
    import copy
    result = copy.deepcopy(base)
    profile=localization.get('scoring_profile',PROFILE)
    if profile not in PROFILES:raise ValueError('Unknown localization report profile')
    expected_base='l2-photo-embodied-v4.0.0' if profile==PHOTO_PROFILE else 'l2-reference-embodied-v4.0.0'
    if base['method_version'] != expected_base:
        raise ValueError('Localization requires the explicit v4 reference base')
    measured = localization.get('status') == 'measured'
    value = localization.get('score')
    if measured and (type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1):
        raise ValueError('Finite localization quality required')
    c = result['score_components'];c['localization'] = value if measured else None
    valid = base['score_valid']
    lower = sum(w*(c.get(k) or 0.) for k, w in WEIGHTS.items())
    for key, weight in WEIGHTS.items():
        c[key+'_weight'] = weight
        c[key+'_contribution'] = weight*(c[key] or 0.) if valid and (key != 'localization' or measured) else None if valid and key == 'localization' else 0.
    result.update(method_version=profile, localization=localization, base_scoring_profile=base['method_version'],
        S_core=lower if valid and measured else 0. if not valid else None,
        S_level=lower if measured else None, S_diagnostic=lower if measured else None,
        quality_lower_bound=lower if valid else 0., status=base['status'] if measured or not valid else 'not_measurable',
        score_scope='60% '+('whole-image appearance' if profile==PHOTO_PROFILE else 'subject appearance')+' + 20% object localization + 10% static support + 10% validity',
        formal_score_eligible=False, localization_complete=measured)
    if 'automatic_S_core' in result:result['automatic_S_core']=result['S_core']
    result['protocol'].update(component_weights=WEIGHTS, main_image_weight=.6, localization_weight=.2,
        localization_method=METHOD)
    result['measurements'].append({'id': 'object_localization', 'status': localization['status'],
        'score': value if measured else None, 'passed': value >= 1.-1e-8 if measured else None,
        'affects_eligibility': False, 'affects_quality': True, 'details': localization})
    result['limitations'] += ['Object boxes compare only main-view identity/location/scale; detector recall is not perfect.',
                             'Missing localization measurement leaves total score unavailable; system validity is retained.']
    return result
