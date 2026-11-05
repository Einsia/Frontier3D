import copy
import pytest
from harness.L3.MinecraftVillage.protocol import REQUIRED, DOORS, VIEWS, make_plans


def bindings():
    return {'version':1,
            'entities':{k:{'approach_cm':[0,0,85],'look_cm':[100,0,100],
                           'crossing_from_cm':[0,0,85],'crossing_to_cm':[200,0,85]} for k in REQUIRED},
            'views':{k:{'position_cm':[0,0,1000],'look_cm':[0,0,0]} for k in VIEWS},
            'journey':[{'direction':[1,0,0],'seconds':1} for _ in range(4)]}


def test_bad_door_is_recorded_without_blocking_other_evidence():
    b=bindings();b['entities'][DOORS[0]]['crossing_to_cm']=[600,0,85]
    original=copy.deepcopy(b)
    with pytest.raises(ValueError,match='crossing'):make_plans(b)
    failures={};plans=make_plans(b,failures=failures)
    assert DOORS[0].replace('.','_') not in plans
    assert set(failures)=={DOORS[0].replace('.','_')}
    assert failures[DOORS[0].replace('.','_')]['status']=='submission_contract_failure'
    assert len(plans)==len(REQUIRED)+1
    assert 'views' in plans and 'journey' in plans and 'house01_chest' in plans
    assert b==original


def test_invalid_journey_does_not_disable_views_or_interactions():
    b=bindings();b['journey'][0]['seconds']=100
    failures={};plans=make_plans(b,failures=failures)
    assert set(failures)=={'journey'}
    assert 'views' in plans and 'house01_door' in plans


def test_valid_partial_and_strict_plans_match():
    b=bindings();failures={}
    assert make_plans(b)==make_plans(b,failures=failures)
    assert not failures
