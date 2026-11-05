import copy
import pytest
from harness.L3.Suite.binding_hints import normalize_bindings, vector3
from harness.L3.Suite.plans import view_plan, local_plan, workflow_plan

def test_canonical_plan_unchanged_and_input_immutable():
    b={"entities":{},"views":{"a":{"position_cm":[1,2,3],"look_cm":[0,0,0]}},"reference_views":{}}
    original=copy.deepcopy(b);n,a=normalize_bindings(b)
    assert n==b==original and not a["normalizations"] and not a["rejected"]
    assert view_plan(n)==view_plan(b)

def test_exact_camera_alias_has_same_executed_plan():
    canonical={"position_cm":[1,2,3],"look_cm":[0,0,0]}
    b={"views":{"a":{"position_cm":[1,2,3],"target_cm":[0,0,0]}}}
    original=copy.deepcopy(b);n,a=normalize_bindings(b)
    assert view_plan(n)[0]==view_plan({"views":{"a":canonical}})[0]
    assert b==original and len(a["normalizations"])==1

def test_unique_records_preserve_coordinates_and_ids():
    b={"entities":[{"id":"door","approach_cm":[1,2,3],"look_cm":[4,5,6]}],
       "views":[{"id":"room","position_cm":[1,2,3],"look_cm":[4,5,6]}]}
    n,a=normalize_bindings(b)
    assert n["entities"]["door"]==b["entities"][0]
    assert n["views"]["room"]==b["views"][0]
    p,m=workflow_plan({**n,"workflow":[{"op":"invoke","target":"door","action":"open"}]},{"entities":[]})
    assert not m["rejected"]

def test_duplicate_ids_and_conflicting_aliases_are_not_guessed():
    n,a=normalize_bindings({"entities":[{"id":"door"},{"id":"door"}],
        "views":{"a":{"position_cm":[1,2,3],"look_cm":[0,0,0],"target_cm":[9,9,9]}}})
    assert not n["entities"] and not n["views"] and len(a["rejected"])==2

@pytest.mark.parametrize("bad",[[1,2],[1,2,float("nan")],[True,2,3],"1,2,3",None])
def test_invalid_vectors_never_invent_height_or_coordinates(bad):
    assert not vector3(bad)
    n,a=normalize_bindings({"entities":{"x":{"approach_cm":bad}},"views":{"v":{"position_cm":bad,"look_cm":[0,0,0]}}})
    assert not n["views"]
    p,m=local_plan(n,{"task_key":"l3-e04","entities":[{"id":"x","role":"movable","actions":["pick_up"]}]})
    assert not p["steps"] and m["entities"][0]["binding_missing"]

def test_string_reference_ids_do_not_create_camera_poses():
    n,a=normalize_bindings({"reference_views":["reference-01"]})
    assert not n["reference_views"] and a["rejected"]

def test_missing_entity_schema_is_not_inferred_from_other_lists():
    n,a=normalize_bindings({"interactables":[{"id":"x","approach_cm":[1,2,3]}]})
    assert n["entities"]=={}

def test_reference_orbits_unchanged_for_exact_alias():
    v={"position_cm":[1,2,3],"look_cm":[4,5,6]}
    alias={"position_cm":v["position_cm"],"target_cm":v["look_cm"]}
    n,a=normalize_bindings({"reference_views":{"r":alias}})
    assert view_plan(n)[0]==view_plan({"reference_views":{"r":v}})[0]
