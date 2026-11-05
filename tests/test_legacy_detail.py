from copy import deepcopy

import pytest

from src.evaluator.legacy_detail import detail_from_criteria, legacy_weights, replace_connection


def source():
    pointer = {'path': '/archive/old.json', 'sha256': 'a' * 64}
    report = {'task_id': 'L1/Image2Code/example', 'method_version': 'legacy', 'score_valid': True,
              'S_core': .5, 'gates': {'execution': {'passed': True}},
              'score_components': {'main_image': .4, 'main_image_weight': .5, 'main_image_contribution': .2,
                                   'localization': .5, 'localization_weight': .2, 'localization_contribution': .1,
                                   'vlm': .5, 'vlm_weight': .2, 'vlm_contribution': .1,
                                   'physics': 1., 'physics_weight': .1, 'physics_contribution': .1}}
    record = {'task_id': report['task_id'], 'model': 'model-a', 'effective_validity': True,
              'source_bindings': {'selected_report': pointer}}
    return report, record, pointer


def apply(report, record, pointer, detail):
    return replace_connection(report, detail, source_report=pointer, detail_record=record, release_id='test')


def test_only_ten_percent_term_changes_and_inputs_remain_intact():
    report, record, pointer = source()
    before = deepcopy(report)
    result = apply(report, record, pointer, {'status': 'measured', 'score': .2})
    assert result['S_core'] == pytest.approx(.42)
    assert result['legacy_replacement']['delta_points'] == pytest.approx(-8)
    assert result['gates'] == before['gates']
    assert 'physics' not in result['component_weights']
    assert result['score_components']['detail_weight'] == .1
    for key, value in before['score_components'].items():
        if not key.startswith('physics'):
            assert result['score_components'][key] == value
    assert report == before


def test_missing_detail_stays_missing_and_true_zero_is_measured():
    report, record, pointer = source()
    assert apply(report, record, pointer, {'status': 'not_measurable', 'score': 0})['S_core'] is None
    assert apply(report, record, pointer, {'status': 'measured', 'score': 0})['S_core'] == pytest.approx(.4)


def test_delivery_failure_retains_zero_without_inventing_detail():
    report, record, pointer = source()
    report.update(score_valid=False, S_core=0)
    record['effective_validity'] = False
    result = apply(report, record, pointer, {'status': 'not_measurable', 'score': None})
    assert result['S_core'] == 0
    assert result['score_components']['detail'] is None
    assert result['score_components']['detail_contribution'] == 0


def test_mismatched_candidate_validity_and_arithmetic_rejected():
    report, record, pointer = source()
    record['source_bindings']['selected_report'] = {**pointer, 'sha256': 'b' * 64}
    with pytest.raises(ValueError, match='candidate'):
        apply(report, record, pointer, {'status': 'measured', 'score': .2})
    record['source_bindings']['selected_report'] = pointer
    record['effective_validity'] = False
    with pytest.raises(ValueError, match='validity'):
        apply(report, record, pointer, {'status': 'measured', 'score': .2})
    record['effective_validity'] = True
    report['S_core'] = .8
    with pytest.raises(ValueError, match='arithmetic'):
        apply(report, record, pointer, {'status': 'measured', 'score': .2})


def test_sceneedit_aggregate_target_weight_is_not_counted_twice():
    report = {'score_components': {'numeric': 1, 'numeric_weight': .2, 'target': .5,
                'target_weight': .5, 'similarity_weight': .3, 'preservation': .9,
                'preservation_weight': .2, 'physics': 1, 'physics_weight': .1,
                'vlm': .3, 'vlm_weight': .2, 'main_image': None, 'main_image_weight': 0}}
    assert legacy_weights(report) == {'numeric': .2, 'target': .3, 'preservation': .2, 'physics': .1, 'vlm': .2}


def test_failed_text_report_without_measurements_keeps_unknown_components():
    report, record, pointer = source()
    report.update(method_version='l1-brief-l2aligned-v1.0.0', score_valid=False, S_core=0, score_components={})
    record['effective_validity'] = False
    result = apply(report, record, pointer, {'status': 'not_measurable', 'score': None})
    assert result['component_weights'] == {'vlm': .6, 'data': .3, 'detail': .1}
    assert result['S_core'] == 0
    assert all(result['score_components'][key] is None for key in ['vlm','data','detail'])


def test_detail_subset_recomputes_each_variant_before_selecting_minimum():
    plan = {'measurements': [{'id': name, 'weight': weight, 'method': 'visual_coverage_deviation'}
                            for name, weight in [('feature', .3), ('appearance', .3)]]}
    result = detail_from_criteria(plan, ['feature'],
        {'primary': {'feature': .9, 'appearance': .1}, 'seed-0': {'feature': .4, 'appearance': 1}},
        ['primary', 'seed-0'])
    assert result['score'] == .4
    assert result['selected_variant'] == 'seed-0'
    assert result['measurements'][0]['weight'] == 1
    missing = detail_from_criteria(plan, ['feature'], {'primary': {'feature': .9}}, ['primary', 'seed-0'])
    assert missing['score'] is None
    assert missing['missing_measurements'] == ['seed-0:feature']


@pytest.mark.parametrize('value', [-.1, 1.1, float('nan'), True])
def test_invalid_detail_rejected(value):
    report, record, pointer = source()
    with pytest.raises(ValueError):
        apply(report, record, pointer, {'status': 'measured', 'score': value})
