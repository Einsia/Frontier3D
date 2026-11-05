from copy import deepcopy
import json
from pathlib import Path
import pytest

from src.evaluator.legacy_detail_v2 import TASK_RULES, COMPONENT_RULES, linear_observations, revise

ROOT = Path(__file__).resolve().parents[1]


def baseline():
    weights={'main_image':.5,'localization':.2,'vlm':.2,'detail':.1}
    return [dict(task_id=task,category=task.split('/')[1],model='synthetic',
        effective_validity=True,components={k:.5 for k in weights},
        component_weights=weights,S_core=.5,score_100=50.)
        for task in [*TASK_RULES, 'L1/Image2Code/task_L1_Image2Code_999']]


def test_exact_scope_preserves_every_other_record():
    unchanged = [r for r in baseline() if r['task_id'] not in TASK_RULES]
    assert len(unchanged) == 1
    for row in unchanged:
        assert revise(row, None) == row
        with pytest.raises(ValueError, match='outside'):
            revise(row, {'invented': 0})


def test_direct_replacement_keeps_localization_and_missing_is_not_zero():
    for row in baseline():
        if row['task_id'] not in TASK_RULES:
            continue
        scores = {key: 1 for key, *_ in TASK_RULES[row['task_id']]}
        result = revise(row, scores)
        assert result['S_core'] == pytest.approx(.8+.2*row['components']['localization'])
        assert result['components']['localization'] == row['components']['localization']
        assert all(result['components'][k] == 1 for k in ('main_image','vlm','detail'))
        missing = revise(row, None)
        assert missing['S_core'] is None
        assert missing['components']['main_image'] is None
        assert missing['components']['localization'] == row['components']['localization']
        assert revise(row, {k: 0 for k in scores})['S_core'] == pytest.approx(.2*row['components']['localization'])
        assert result['component_weights'] == row['component_weights']
        invalid = {**row, 'effective_validity': False, 'S_core': 0, 'score_100': 0}
        assert revise(invalid, scores)['S_core'] == 0


def test_one_observation_changes_exactly_one_component():
    for row in baseline():
        task=row['task_id']
        if task not in TASK_RULES:
            continue
        scores = {key: .5 for key, *_ in TASK_RULES[task]}
        first=revise(row,scores)
        for owner,rules in COMPONENT_RULES[task].items():
            for key,weight in rules:
                second=revise(row,{**scores,key:0})
                assert {k for k in first['components'] if first['components'][k] != second['components'][k]} == {owner}
                assert first['S_core']-second['S_core'] == pytest.approx(row['component_weights'][owner]*weight*.5)


def test_rule_does_not_use_model_or_original_replaced_values():
    row = next(r for r in baseline() if r['task_id'] in TASK_RULES)
    scores = {key: .25 for key, *_ in TASK_RULES[row['task_id']]}
    alternate = deepcopy(row)
    alternate['model'] = 'unseen-model'
    for k in ('main_image','vlm','detail'):alternate['components'][k] = 1
    alternate['S_core'] = sum(alternate['components'][k]*w for k,w in alternate['component_weights'].items())
    alternate['score_100'] = 100*alternate['S_core']
    assert revise(row, scores)['score_100'] == revise(alternate, scores)['score_100']
    for bad in [float('nan'), -1, 1.01, True]:
        with pytest.raises(ValueError):revise(row, {k:bad for k in scores})
    with pytest.raises(ValueError):revise(row,{})


@pytest.mark.parametrize('c,e,expected', [(0,0,0),(.5,.5,.25),(1,.5,.5),(1,0,1)])
def test_linear_quality_anchors(c,e,expected):
    task=next(iter(TASK_RULES))
    criteria=[{'check_id':key,'coverage':c,'deviation':e,'score':999} for key,*_ in TASK_RULES[task]]
    assert set(linear_observations(task,criteria).values()) == {expected}
    with pytest.raises(ValueError):linear_observations(task,criteria[:-1])


def test_same_rubric_all_models_and_no_criterion_double_assignment():
    for task in TASK_RULES:
        expected={key for key,*_ in TASK_RULES[task]}
        actual=[key for rules in COMPONENT_RULES[task].values() for key,_ in rules]
        assert len(actual)==len(expected) and set(actual)==expected
