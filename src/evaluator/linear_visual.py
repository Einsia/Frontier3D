"""Independent visual dimensions with linear fidelity, preserving strict v1."""
from copy import deepcopy
import math

from src.agent_judge import strict_continuous, task_continuous
from .legacy_detail import ratio
from .strict_visual import IMAGE_CATEGORIES, weighted

VERSION = 'linear-visual-20261018-v1'
IMAGE_WEIGHTS = {'main_image': .3, 'detail': .3, 'localization': .2, 'vlm': .2}


def linear_spec(source):
    """Keep every public feature and evidence requirement; version the formula."""
    strict_continuous.validate_spec(source)
    result = deepcopy(source)
    result.update(protocol=task_continuous.PROTOCOL, release_id=VERSION,
                  authoring='fixed_public_features_linear_fidelity_independent_dimensions')
    return task_continuous.validate_spec(result)


def replay_observations(response, source_spec, evidence_paths):
    """Explicit migration of raw c/e observations, never relabel an old score."""
    original = strict_continuous.score(response, source_spec, evidence_paths)
    answer = deepcopy(response)
    answer['protocol'] = task_continuous.PROTOCOL
    result = task_continuous.score(answer, linear_spec(source_spec), evidence_paths)
    result.update(source_protocol=original['protocol'], observation_reuse=True,
                  score_rule='coverage * (1 - deviation)', new_model_calls=0)
    return result


def aggregate(category, level, original, original_weights, *, detail, vlm, content=None, valid):
    components, weights = dict(original), dict(original_weights)
    if category != 'CodeEdit':
        components.update(detail=detail, vlm=vlm)
    if category in IMAGE_CATEGORIES:
        weights = dict(IMAGE_WEIGHTS)
        components = {key: components.get(key) for key in weights}
    elif level in {2, 'L2'} and category == 'Brief2Scene':
        # This task's explicit inventory cross-check is outside the image change.
        components['data'] = (None if content is None or original.get('data') is None
                              else ratio(content) * ratio(original['data']))
    if set(components) != set(weights) or not math.isclose(sum(weights.values()), 1, abs_tol=1e-10):
        raise ValueError('Component population/weights differ')
    for value in components.values():
        if value is not None:
            ratio(value)
    missing = [k for k, v in components.items() if v is None]
    score = 0. if valid is False else None if valid is not True or missing else math.fsum(
        weights[k] * components[k] for k in weights)
    groups = {}
    if category in IMAGE_CATEGORIES:
        groups['image_similarity'] = {'weight': .6, 'children': ['main_image', 'detail'],
            'value': None if components['main_image'] is None or detail is None
                     else (components['main_image'] + detail) / 2}
    return {'components': components, 'component_weights': weights, 'S_core': score,
            'score_100': None if score is None else 100 * score,
            'missing_components': missing, 'component_groups': groups,
            'diagnostics': {'original_components': dict(original), 'content_fidelity': content,
                            'image_content_multiplier': False}}


def variant_components(groups, judgments, native=None):
    """The declared variant/criterion population stays fixed, including absences."""
    native = native or {}
    values = {'detail': {}, 'vlm': {}, 'content': {}}
    for variant, dimensions in groups.items():
        result = judgments.get(variant)
        for dimension, weights in dimensions.items():
            if not weights:
                continue
            weights = dict(weights)
            observations = {k: None if result is None else result['criterion_scores'].get(k)
                            for k in weights}
            if dimension == 'detail':
                for k, item in native.items():
                    weights[k] = item['weight']
                    observations[k] = item['values'].get(variant, {}).get('value')
            values[dimension][variant] = weighted(observations, weights)
    selected = {k: min(v, key=v.get) if v and all(x is not None for x in v.values()) else None
                for k, v in values.items()}
    minimum = {k: values[k][variant] if variant else None for k, variant in selected.items()}
    return minimum, selected, values
