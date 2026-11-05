"""L1 adapters for the published L2 Reference v7.1 / Brief v7 quality contract.

This is a new measurement protocol, NOT a reweighting of an old L1 total.
Inputs to aggregate() must come from the trusted evaluator/orchestrator, never
candidate-authored JSON. Missing collectors block a new total/publication.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from statistics import mean

from src.agent_judge import l2_rubric
from src.agent_judge.protocol import contract_hash

from .l2_reference_boxes import POLICY as BOX_POLICY
from .l2_reference_boxes import validate_annotation as validate_boxes
from .l2_reference_regions import METHOD as IMAGE_METHOD
from .l2_reference_regions import regional_components
from .l2_reference_regions import validate_annotation as validate_regions
from .l2_vlm_scoring import PROFILES as L2_PROFILES

VERSION = 'l1-l2-alignment-plan-v1'
REFERENCE = 'l1-reference-l2aligned-v1.0.0'
BRIEF = 'l1-brief-l2aligned-v1.0.0'
PROFILES = {
    REFERENCE: ('l2-reference-localized-vlm-v7.1.0', {'main_image': .5, 'localization': .2, 'physics': .1, 'vlm': .2}),
    BRIEF: ('l2-brief-vlm-v7.0.0', {'vlm': .6, 'data': .3, 'physics': .1}),
}
CATEGORIES = {'Image2Code': REFERENCE, 'Image2Code-SingleView': REFERENCE, 'Text2Code': BRIEF}
SYSTEM_GATES = ('execution', 'artifacts', 'real_geometry', 'integrity', 'all_seeds', 'all_seed_quality')
METHODS = {'main_image': IMAGE_METHOD, 'data': 'l1-content-measurements-v1', 'physics': 'l1-assembly-support-v1'}
UNKNOWN = {'not_measurable', 'not_implemented', 'infrastructure_error'}
SEMANTIC_EXCLUSIONS = {'glb_readable', 'reconstruction', 'instructions', 'procedural_materials', 'seed_quality'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def validate_plan(plan):
    profile = CATEGORIES.get(plan.get('category'))
    if profile is None or plan.get('version') != VERSION or plan.get('profile') != profile:
        raise ValueError('Unsupported L1 category/alignment version (CodeEdit is unchanged)')
    baseline, weights = PROFILES[profile]
    if plan.get('l2_baseline') != baseline or plan.get('weights') != weights or L2_PROFILES[baseline][2] != weights:
        raise ValueError('L2 baseline/weight drift; freeze a new version')
    if not plan.get('task_id', '').startswith('L1/'+plan['category']+'/'):
        raise ValueError('L1 task/category identity mismatch')
    if plan.get('validity_policy') != 'system_gates_no_quality_credit' or plan.get('missing_policy') != l2_rubric.MISSING_POLICY:
        raise ValueError('Validity/missing policy drift')
    if plan.get('quality_population') != 'accepted_baseline_seed_checks_are_system_evidence':
        raise ValueError('L2 judges the accepted canonical candidate, not best-of seeds')
    if plan.get('localization_policy') != (BOX_POLICY if profile == REFERENCE else None):
        raise ValueError('Localization must reuse the L2 instance-matching policy')
    checks = plan.get('automatic_checks', [])
    if (profile == BRIEF and not checks) or len(set(checks)) != len(checks):
        raise ValueError('Explicit distinct automatic content checks required')
    if profile == REFERENCE and checks:
        raise ValueError('Image content checks are not an additional weighted component')
    return plan


def make_plan(manifest, spec, source_hashes, content_checks):
    category = manifest['category']
    if category not in CATEGORIES:
        raise ValueError('Only Image2Code, SingleView and Text2Code are in scope')
    profile = CATEGORIES[category]
    baseline, weights = PROFILES[profile]
    raw = spec.to_dict()
    requirements = raw['l1_protocol']['requirements']
    return validate_plan({
        'version': VERSION, 'task_id': manifest['id'], 'category': category, 'title': manifest['title'],
        'profile': profile, 'l2_baseline': baseline, 'weights': copy.deepcopy(weights),
        'spec_sha256': spec.digest, 'sources': dict(source_hashes),
        'validity_policy': 'system_gates_no_quality_credit', 'missing_policy': l2_rubric.MISSING_POLICY,
        'quality_population': 'accepted_baseline_seed_checks_are_system_evidence',
        'localization_policy': copy.deepcopy(BOX_POLICY) if profile == REFERENCE else None,
        'automatic_checks': list(content_checks) if profile == BRIEF else [],
        'reference_primary': raw.get('reference_images', {}).get('primary'),
        'render_views': copy.deepcopy(raw['render_views']), 'seeds': list(spec.seeds),
        'unverified_requirements': [r for r in requirements if r.get('implementation') != 'complete'],
        'physics': {'method': METHODS['physics'], 'review_status': 'pending', 'policy': None,
                    'frame': None, 'datum': None,
                    'reason': 'Freeze L1 assembled/support context and metre-valued tolerance; no automatic L2 2cm or floor assumption.'},
        'reference_regions': None, 'reference_boxes': None,
        'vlm_spec_digest': None,
        'formal_score_eligible': False,
    })


def rubric(plan, instruction, requirements, annotation=None):
    """Reuse exactly the L2 0..4 anchors and family-level dimension weights."""
    validate_plan(plan)
    if hashlib.sha256(instruction.encode()).hexdigest() != plan['sources']['instruction.md']:
        raise ValueError('Rubric instruction changed')
    brief = plan['profile'] == BRIEF
    if not brief:
        if not annotation:
            raise ValueError('Reference-only localization definitions must be frozen first')
        validate_boxes(annotation)
        if annotation['task_id'] != plan['task_id'] or annotation['reference_sha256'] != plan['sources'][plan['reference_primary']]:
            raise ValueError('Reference annotation belongs to a different task/image')
        definitions = [('subject_fidelity', 'reference_fidelity', .4, 'Compare key subject identity, distinctive form, completeness and visible parts with the ORIGINAL reference. Generic same-category primitives are insufficient.'),
                       ('composition_fidelity', 'reference_layout', .3, 'Compare framing, relative position, scale, depth and occlusion on the original pixel grid. Do not align the images.'),
                       ('appearance_fidelity', 'reference_appearance', .3, 'Compare materials, colors, lighting, contrast and rendering style against the ORIGINAL reference.')]
    else:
        semantic = [r for r in requirements if r.get('applicable', True) and r['id'] not in SEMANTIC_EXCLUSIONS]
        if not semantic:
            raise ValueError('Text task needs task-specific semantic criteria')
        definitions = [(r['id'], 'instruction_following', .6/len(semantic), r['text']+' Evaluate visible fulfilment only; exact dimensions and hidden geometry require independent measurements, not pixel guesses.') for r in semantic]
        definitions += [(identity, 'aesthetics', .1, question) for identity, question in [
            ('aesthetic_composition', 'Grade authored composition, framing, focal hierarchy and readability of the intended object/assembly.'),
            ('aesthetic_light_color', 'Grade light/shadow shaping, exposure and color harmony within the requested style.'),
            ('aesthetic_finish', 'Grade visible shape/material finish, clean joins, proportions and intentional detail; complexity alone earns nothing.'),
            ('aesthetic_coherence', 'Grade coherent overall design and presentation; allow every design satisfying the written brief.')]]
    result = {'protocol': l2_rubric.PROTOCOL, 'case_id': plan['task_id'],
              'family': 'Brief2Scene' if brief else 'Reference2Scene',
              'instruction_sha256': contract_hash(instruction),
              'reference_policy': 'Written brief only; NEVER show a private reference design to the text judge.' if brief else 'Compare original public reference to accepted candidate main.png; other views are supplementary only.',
              'focus': 'L1 object/assembly task. Do not require a room or scene population. Exact tolerances remain automatic. Use authored appearance for aesthetics, not diagnostic silhouette masks.',
              'missing_policy': l2_rubric.MISSING_POLICY, 'anchors': copy.deepcopy(l2_rubric.ANCHORS),
              'checks': [{'id': identity, 'dimension': dimension, 'weight': weight, 'question': question, 'units': [identity]}
                         for identity, dimension, weight, question in definitions],
              'localization': None if brief else copy.deepcopy(annotation)}
    return l2_rubric.validate_spec(result)


def measure_data(plan, checks):
    """Only predeclared implemented content measurements; no legacy S_core reuse."""
    validate_plan(plan)
    if plan['profile'] != BRIEF:
        raise ValueError('Text-only data measurement')
    selected = {name: checks.get(name, {}) for name in plan['automatic_checks']}
    missing = [name for name, row in selected.items()
               if row.get('measurement_status', row.get('status')) not in {'passed', 'failed', 'measured'} or not finite(row.get('score'))]
    return {'method': METHODS['data'], 'status': 'not_measurable' if missing else 'measured',
            'score': None if missing else mean(r['score'] for r in selected.values()),
            'check_ids': list(selected), 'missing_checks': missing, 'measurements': copy.deepcopy(selected),
            'scope': 'Equal-weight implemented content proxies only; see unverified_requirements. Not exact CAD completion.'}


def measure_image(plan, reference, candidate, annotation, *, image_sha256):
    validate_plan(plan)
    if plan['profile'] != REFERENCE or not plan.get('reference_regions'):
        raise ValueError('Freeze reference regions before image measurement')
    validate_regions(annotation)
    if digest(annotation) != plan['reference_regions'] or annotation['task_id'] != plan['task_id'] or annotation['reference_sha256'] != plan['sources'][plan['reference_primary']]:
        raise ValueError('Reference region binding mismatch')
    if reference.shape != candidate.shape:
        raise ValueError('Native pixel grids differ; fitting/resizing is forbidden')
    return {'status': 'measured', **regional_components(reference, candidate, annotation),
            'annotation_sha256': digest(annotation), 'image_sha256': image_sha256}


def bind_reference(plan, instruction, requirements, boxes, regions):
    """Freeze evaluator-owned reference definitions before any candidate review."""
    validate_plan(plan)
    if plan['profile'] != REFERENCE:
        raise ValueError('Reference bindings cannot be added to a text task')
    validate_boxes(boxes)
    validate_regions(regions)
    for annotation in (boxes, regions):
        if annotation['task_id'] != plan['task_id'] or annotation['reference_sha256'] != plan['sources'][plan['reference_primary']]:
            raise ValueError('Reference definitions must bind this task and original image')
    frozen = copy.deepcopy(plan)
    frozen.update(reference_boxes=digest(boxes), reference_regions=digest(regions))
    spec = rubric(frozen, instruction, requirements, boxes)
    frozen['vlm_spec_digest'] = digest(spec)
    return frozen, spec


def aggregate(plan, gates, measurements, judgment, *, artifact_sha256):
    """Replay trusted measurements under new weights, preserving unknowns.

    Do not feed a Text2Code legacy requirements gate here: content failures are
    not system failures. Collect the six system-only gates independently.
    """
    validate_plan(plan)
    if set(gates) != set(SYSTEM_GATES):
        raise ValueError('Exactly the six system-only gates are required')
    states = []
    for name, row in gates.items():
        state = row.get('measurement_status')
        if state not in {'passed', 'failed', *UNKNOWN} or row.get('passed') is not (state == 'passed'):
            raise ValueError('Invalid system gate: '+name)
        states.append(state)
    weights = plan['weights']
    values, detail = {}, {}
    for key in weights.keys()-{'vlm', 'localization'}:
        row = copy.deepcopy(measurements.get(key, {}))
        if row and row.get('method') != METHODS[key]:
            raise ValueError('Wrong measurement algorithm: '+key)
        measured = row.get('status') == 'measured'
        if measured and not finite(row.get('score')):
            raise ValueError('Measured component must be a finite unit score')
        if measured and key == 'main_image' and (not plan.get('reference_regions') or row.get('annotation_sha256') != plan['reference_regions'] or row.get('image_sha256') != artifact_sha256.get('main.png')):
            raise ValueError('Image must bind frozen regions and audited candidate')
        if measured and key == 'data' and row.get('check_ids') != plan['automatic_checks']:
            raise ValueError('Automatic content population changed')
        if measured and key == 'physics' and (plan['physics']['review_status'] != 'approved' or not plan['physics'].get('policy') or row.get('context_sha256') != digest(plan['physics']) or not artifact_sha256.get('scene.blend') or row.get('scene_sha256') != artifact_sha256['scene.blend']):
            raise ValueError('Physical measurement needs reviewed task context and native binding')
        values[key] = row['score'] if measured else None
        detail[key] = row or {'status': 'not_measurable', 'reason': 'Collector/evidence not available'}
    judged = judgment is not None and judgment.get('status') == 'scored'
    if judged and (judgment.get('protocol') != l2_rubric.PROTOCOL or judgment.get('case_id') != plan['task_id'] or not finite(judgment.get('S_vlm')) or not artifact_sha256.get('main.png') or judgment.get('image_sha256') != artifact_sha256['main.png'] or not plan.get('vlm_spec_digest') or judgment.get('vlm_spec_digest') != plan['vlm_spec_digest'] or judgment.get('alignment_plan_sha256') != digest(plan)):
        raise ValueError('Judgment must bind the L2 rubric, L1 identity and audited candidate image')
    values['vlm'] = judgment['S_vlm'] if judged else None
    if 'localization' in weights:
        loc = (judgment or {}).get('localization', {})
        ready = judged and loc.get('status') == 'measured'
        if ready and (loc.get('method') != 'vlm-grounded-reference-boxes-v2' or not finite(loc.get('score')) or loc.get('image_sha256') != artifact_sha256.get('main.png') or not plan.get('reference_boxes') or judgment.get('annotation_sha256') != plan['reference_boxes']):
            raise ValueError('Localization must bind frozen boxes and the same candidate')
        values['localization'] = loc['score'] if ready else None
    failed = 'failed' in states
    system_valid = all(state == 'passed' for state in states)
    missing = [key for key in weights if values[key] is None]
    complete = system_valid and not missing
    total = 0. if failed else sum(weights[k]*values[k] for k in weights) if complete else None
    components = {}
    for key, weight in weights.items():
        components.update({key: values[key], key+'_weight': weight,
                           key+'_contribution': 0. if failed else weight*values[key] if values[key] is not None else None})
    return {'task_id': plan['task_id'], 'spec_sha256': plan['spec_sha256'],
            'method_version': plan['profile'], 'l2_baseline': plan['l2_baseline'], 'plan_sha256': digest(plan),
            'status': 'system_invalid' if failed else 'scored' if complete else 'not_measurable',
            'S_core': total, 'S_level': total, 'score_components': components,
            'score_valid': system_valid, 'measurement_complete': complete or failed,
            'system_validity': 'failed' if failed else 'passed' if system_valid else 'unknown',
            'case_pass': system_valid, 'case_pass_meaning': 'System validity only, never content correctness',
            'gates': copy.deepcopy(gates), 'measurements': detail, 'missing_components': missing,
            'artifact_sha256': copy.deepcopy(artifact_sha256), 'vlm_judgment': copy.deepcopy(judgment),
            'protocol': {'component_weights': copy.deepcopy(weights), 'evaluation_mode': 'l2_aligned_quality',
                         'quality_population': plan['quality_population'], 'seed_checks_remain_required': True},
            'unverified_requirements': copy.deepcopy(plan['unverified_requirements']),
            'formal_score_eligible': False, 'full_task_verified': False,
            'limitations': ['L2 weights and criterion rules do not certify L1 hidden geometry or complete CAD correctness.',
                            'New reference regions, grounding, physical context and VLM evidence are required; old totals cannot be reweighted.',
                            'Reference annotations and judge grades require human calibration.']}
