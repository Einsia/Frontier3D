"""303-result revision: 30% appearance + 30% detail, strict VLM and content."""
import math

from .legacy_detail import ratio

IMAGE_CATEGORIES = {'Image2Code', 'Image2Code-SingleView', 'Reference2Scene', 'Reference2Scene-RealPhoto'}
VERSION = 'strict-visual-20261018-v1'


def weighted(values, weights):
    if set(values) != set(weights) or not weights:
        raise ValueError('Fixed scoring population changed')
    if any(v is None for v in values.values()):
        return None
    if any(ratio(w) <= 0 for w in weights.values()):
        raise ValueError('Positive weights required')
    return math.fsum(ratio(values[k]) * w for k, w in weights.items()) / math.fsum(weights.values())


def aggregate(category, level, old_components, old_weights, *, detail, vlm, content, valid):
    components, weights = dict(old_components), dict(old_weights)
    diagnostics = {'original_components': dict(old_components), 'content_fidelity': content}
    if category != 'CodeEdit':
        components.update(detail=detail, vlm=vlm)
    if category in IMAGE_CATEGORIES:
        weights = {'main_image': .3, 'detail': .3, 'localization': .2, 'vlm': .2}
        for key in ('main_image', 'localization'):
            components[key] = None if content is None or old_components.get(key) is None else ratio(content) * ratio(old_components[key])
    elif level in {2, 'L2'} and category == 'Brief2Scene':
        components['data'] = None if content is None or old_components.get('data') is None else ratio(content) * ratio(old_components['data'])
    if set(components) != set(weights) or not math.isclose(sum(weights.values()), 1, abs_tol=1e-10):
        raise ValueError('Component population/weights differ')
    for value in components.values():
        if value is not None:
            ratio(value)
    missing = [k for k, v in components.items() if v is None]
    score = 0. if not valid else None if missing else math.fsum(components[k] * w for k, w in weights.items())
    groups = {}
    if category in IMAGE_CATEGORIES:
        groups = {'image_similarity': {'weight': .6, 'children': ['main_image', 'detail'],
                   'value': None if components['main_image'] is None or detail is None else (components['main_image'] + detail) / 2}}
    return {'components': components, 'component_weights': weights, 'S_core': score,
            'score_100': None if score is None else 100 * score, 'missing_components': missing,
            'component_groups': groups if category in IMAGE_CATEGORIES else {}, 'diagnostics': diagnostics}
