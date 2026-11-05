import copy,numpy as np
from src.evaluator.l2_physical import DEFAULT_POLICY,physical_plausibility
from tests.l3.geometry_fixtures import box, mesh

def scene():
    v=np.array([[30,30,-40],[40,30,-39],[30,40,-30],[35,35,20]],float)
    mountain=v[np.array([[0,1,2],[0,3,1],[1,3,2],[2,3,0]])]
    return {"scene":{"objects":{"floor":mesh(box([-10,-10,-.5],[10,10,0])),
      "supported":mesh(box([0,0,0],[1,1,1])),
      "floating":mesh(box([3,0,1],[4,1,2])),
      "mountain":mesh(mountain)}}}

def test_explicit_actual_ground_preserves_contact_failures():
    e=scene()
    assert physical_plausibility(e,DEFAULT_POLICY)["status"]=="not_measurable"
    e["reviewed_ground"]={"roots":[{"object":"floor","piece":0,"bounds_m":[[-10,-10,-.5],[10,10,0]]}]}
    r=physical_plausibility(e,DEFAULT_POLICY)
    assert r["status"]=="measured"
    assert r["ground_inference"]=="reviewed_measured_terrain"
    bad={x["object"] for x in r["unsupported"]}
    assert "floating" in bad and "supported" not in bad
    assert r["contact_tolerance_m"]==.02
    e["reviewed_ground"]["roots"][0]["bounds_m"][1][2]=1
    assert physical_plausibility(e,DEFAULT_POLICY)["status"]=="not_measurable"

def test_mask_refresh_cannot_change_interaction_observer():
    from tools.refresh_l3_mask_observer import nonmask_source
    a='head\n    if(Op==TEXT("instance_masks")) {old}\n    if(Op==TEXT("ray")) {ray}\n'
    b=a.replace("{old}","{new}")
    assert nonmask_source(a)==nonmask_source(b)
    assert nonmask_source(a)!=nonmask_source(b.replace("{ray}","{changed}"))
