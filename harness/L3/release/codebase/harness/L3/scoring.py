"""L3 reporting contract: evidence families stay separate; weights are undecided.

This module structures reports, not a geometry oracle. Pending measurements must
remain pending until an evaluator-owned, calibrated measurement supplies them.
"""
from __future__ import annotations

RUBRIC_AXES = ('beauty', 'prompt_alignment', 'style_consistency')


def metric_template(input_mode: str) -> dict:
    if input_mode not in {'image', 'text'}:
        raise ValueError('input_mode must be image or text')
    reference = {
        name: {'status': 'pending_annotations' if input_mode == 'image' else 'not_applicable',
               'value': None}
        for name in ('environment', 'objects')
    }
    return {
        'schema_version': 2,
        'input_mode': input_mode,
        'score': None,
        'weights': None,
        'aggregation_status': 'weights_pending',
        'deterministic': {
            'layout': {'status': 'pending_geometry_and_rules', 'value': None},
            'interaction': {'status': 'pending_runtime_validation', 'value': None},
            'reference_accuracy': reference,
        },
        'rubrics': {name: {'status': 'pending_judgment', 'value': None, 'scale': [0, 4]}
                    for name in RUBRIC_AXES},
    }


def rubric_results(visual: dict) -> dict:
    result = {}
    for name in RUBRIC_AXES:
        verdict = visual.get('verdicts', {}).get(name)
        if verdict is None:
            result[name] = {'status': 'pending_judgment', 'value': None, 'scale': [0, 4]}
            continue
        value = verdict.get('median')
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 4):
            raise ValueError('Invalid rubric value: ' + name)
        needs_review = value is None or verdict.get('needs_human_review', True)
        result[name] = {'status': 'needs_review' if needs_review else 'judged',
                        'value': None if needs_review else value, 'scale': [0, 4],
                        'range': verdict.get('range'), 'source': 'vlm'}
    return result
