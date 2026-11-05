"""October L2 reference contract: local textures and independently matched views.

The final 50/20/10/20 blend is unchanged. This automatic base deliberately leaves
localization for the strict judge; it never fabricates a missing measurement.
"""
import hashlib
import json
from pathlib import Path

from .l2 import score_l2
from .l2_physical import DEFAULT_POLICY, physical_plausibility
from .l2_reference_boxes import validate_annotation
from .l2_reference_regions import validate_annotation as validate_regions

PROFILES = {
    'l2-reference-refresh-v1.0.0': 'Reference2Scene',
    'l2-photo-refresh-v1.0.0': 'Reference2Scene-RealPhoto',
}


def load_plan(root, policy, plan):
    root = Path(root)
    profile = policy['scoring_profile']
    if plan['category'] != PROFILES[profile] or plan['task_id'] != policy['task_id']:
        raise ValueError('Refresh plan identity mismatch')
    if plan.get('version') != 'l2-method-plan-v1' or plan.get('physics') != DEFAULT_POLICY:
        raise ValueError('Version-bound refresh methods required')
    if plan.get('material_policy') != {'image_textures': True, 'packed_dependencies': True,
                                     'whole_reference_projection': False}:
        raise ValueError('Refresh material contract changed')
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(root/'harness/methods.json') != policy['methods_sha256']:
        raise ValueError('Refresh methods changed')
    if set(plan['sources']) != {'instruction.md', 'solution/EVALUATION.md'}:
        raise ValueError('Both task contracts must be bound')
    for name, expected in plan['sources'].items():
        if digest(root/name) != expected:
            raise ValueError('Refresh source changed: '+name)
    views = plan['appearance_views']
    if [v['artifact'] for v in views] not in [['main.png'], ['main.png', 'alternate.png']]:
        raise ValueError('Only supplied corresponding views may be compared')
    for view in views:
        ref = (root/view['reference_path']).resolve()
        if not ref.is_relative_to((root/'environment/input').resolve()) or digest(ref) != view['reference_sha256']:
            raise ValueError('Public reference changed')
        if view['method'] not in {'native-appearance-v1', 'reference-regions-v1'}:
            raise ValueError('Unknown appearance method')
        if view['method'] == 'reference-regions-v1':
            validate_regions(view['annotation'])
            if view['annotation']['reference_sha256'] != view['reference_sha256']:
                raise ValueError('Reference-region binding mismatch')
    boxes = json.loads((root/'harness/reference_boxes.json').read_text())
    validate_annotation(boxes)
    if boxes['reference_sha256'] != views[0]['reference_sha256'] or boxes != plan['vlm_judge']['spec']['localization']:
        raise ValueError('Judge and automatic reference bindings disagree')
    return plan


def compare_views(evidence, plan):
    from .l2_method_scoring import compare_main_image
    rows = []
    for view in plan['appearance_views']:
        remapped = {**evidence,
            'reference_images': {'main': evidence.get('reference_images', {}).get(view['reference_key'])},
            'artifacts': {'main.png': evidence.get('artifacts', {}).get(view['artifact'])}}
        result = compare_main_image(remapped, view['method'], view.get('annotation'))
        # In action-state photos only frozen static regions enter the image
        # grade. The global term would otherwise penalize permitted motion.
        if view.get('static_regions_only') and result.get('status') == 'measured':
            result['score'] = result['subject_score']
            result['weights'] = {'reference_regions': 1., 'whole_image': 0.}
        rows.append({'artifact': view['artifact'], 'reference_key': view['reference_key'], **result})
    complete = all(r['status'] == 'measured' for r in rows)
    return {'status': 'measured' if complete else 'not_measurable',
        'score': sum(r['score'] for r in rows)/len(rows) if complete else None,
        'views': rows, 'view_weights': [1/len(rows)]*len(rows),
        'alignment': 'Native pixel grids; no fitted crop, scale, pose or registration',
        'heldout_used': False}


def score(spec, evidence, policy, plan, *, execution_required=True):
    result = score_l2(spec, evidence)
    image = compare_views(evidence, plan)
    physics = physical_plausibility(evidence, plan['physics'])
    checks = [c for module in result['modules'].values() for c in module['checks']]
    required = [c for c in checks if c['id'].endswith(('_native_size', '_png'))]
    comparable = image['status'] == 'measured'
    valid = all(c['passed'] for c in required) and comparable
    gates = {k: result['gates'][k] for k in
             ('execution', 'artifacts', 'real_geometry', 'integrity', 'all_seeds', 'all_seed_quality')}
    gates['measured_requirements'] = {'passed': valid,
        'required': [c['id'] for c in required]+['reference_views_comparable'],
        'failed': [c['id'] for c in required if not c['passed']]+([] if comparable else ['reference_views_comparable'])}
    eligible = all(g['passed'] for g in gates.values()) if execution_required else (
        valid and gates['artifacts']['passed'] and gates['real_geometry']['passed'])
    measurements = [{'id': c['id'], 'passed': c['passed'], 'score': c['score'],
        'status': c['status'], 'details': c['details'],
        'affects_eligibility': c in required, 'affects_quality': False} for c in checks]
    measurements.append({'id': 'physical_plausibility', **physics,
        'passed': physics['score'] >= 1-1e-8, 'details': physics,
        'affects_eligibility': False, 'affects_quality': True})
    result.update(method_version=policy['scoring_profile'], gates=gates,
        score_valid=eligible, case_pass=eligible, G=int(eligible), task_quality_pass=valid,
        S_core=None if eligible else 0., S_level=None, S_diagnostic=None,
        status='awaiting_localization_and_vlm' if eligible else 'failed',
        measurements=measurements, main_image_comparison=image, physical_plausibility=physics,
        score_components={'main_image': image['score'], 'physics': physics['score'], 'localization': None},
        calibration_status='pilot_reference_only_ai_annotations_human_calibration_pending',
        formal_score_eligible=False, score_scope='Frozen reference appearance and support; judge supplies localization and fidelity',
        text_semantics_evaluated=False, deferred_requirements=[],
        limitations=['No calibrated hidden 3D ground truth; image/box measurements remain visual proxies.',
                    'Novel output is independently rerendered, never pixel-compared to uncalibrated heldout photos.'])
    return result
