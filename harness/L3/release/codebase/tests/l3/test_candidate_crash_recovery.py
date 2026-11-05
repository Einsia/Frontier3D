import json
from harness.L3.Suite.crash_recovery import crashing_invoke,checked_crashes
from harness.L3.MinecraftVillage.protocol import digest

def test_only_dispatch_assertions_are_attributed_to_candidate(tmp_path):
    plan={"steps":[{"op":"snapshot","name":"before"},{"op":"invoke","name":"call","target":"bed","action":"set_height"}]}
    (tmp_path/"before.json").write_text("{}")
    log=tmp_path/"editor.log"
    log.write_text("Assertion failed: Pair libUnrealEditor-L3Environment.so!HandleInteraction")
    assert crashing_invoke(tmp_path,plan)["name"]=="call"
    log.write_text("Out of memory")
    assert crashing_invoke(tmp_path,plan) is None
    log.write_text("Assertion failed: Pair libUnrealEditor-L3Environment.so!HandleInteraction")
    (tmp_path/"before.json").unlink()
    assert crashing_invoke(tmp_path,plan) is None

def test_crash_receipt_requires_same_candidate_and_unchanged_log(tmp_path):
    (tmp_path/"source.json").write_text('{"source_sha256":"source"}')
    log=tmp_path/"editor.log";log.write_text("candidate assertion")
    receipt={"source_sha256":"source","probes":{"call":{"log":"editor.log","log_sha256":digest(log)}}}
    (tmp_path/"crash-probes.json").write_text(json.dumps(receipt))
    assert "call" in checked_crashes(tmp_path)
    log.write_text("changed")
    import pytest
    with pytest.raises(ValueError,match="provenance"):checked_crashes(tmp_path)

def test_crash_is_scored_as_failure_even_if_replay_snapshots_are_unchanged(tmp_path,monkeypatch):
    import harness.L3.Suite.measure as m
    from harness.L3.Suite.policy import write
    write(tmp_path/"source.json",{"source_sha256":"source"})
    log=tmp_path/"editor.log";log.write_text("assertion")
    names=["constraint_00","e000_a0","e000_invalid"]
    write(tmp_path/"crash-probes.json",{"source_sha256":"source","probes":{
        n:{"log":"editor.log","log_sha256":digest(log)} for n in names}})
    write(tmp_path/"contract.json",{"entities":[{"id":"bed","role":"adjustable_bed"}]})
    write(tmp_path/"workflow-metadata.json",{"steps":[],"rejected":[]})
    write(tmp_path/"local-metadata.json",{"constraints":[{"name":"constraint_00","id":"bed"}],
        "entities":[{"id":"bed","prefix":"e000","actions":["set_height"],
        "positive":[{"name":"e000_a0","action":"set_height"}],"invalid_probe":"e000_invalid"}]})
    write(tmp_path/"workspace/project/bindings.json",{})
    write(tmp_path/"workspace/episodes/workflow/completed.json",{"completed":True})
    monkeypatch.setattr(m,"read_frame",lambda *a:{"entities":[{"id":"bed"}]})
    monkeypatch.setattr(m,"parts",lambda *a:[{}])
    monkeypatch.setattr(m,"physical_effect",lambda *a:True)
    monkeypatch.setattr(m,"negative_unchanged",lambda *a:True)
    monkeypatch.setattr(m,"goals",lambda *a:[{"passed":False}])
    result=m.observations(tmp_path)
    target=result["targets"]["bed"]
    assert target["checks"]["positive_physical_effect"]==0
    assert target["invalid_action_rejected"] is False
    assert target["prerequisites"][0]["passed"] is False
    assert target["checks"]["invalid_reach_rejected"]==1/3

def test_mutable_shutdown_log_does_not_change_frozen_crash_receipt(tmp_path):
    from harness.L3.Suite.policy import write
    runtime=tmp_path/"editor.log";runtime.write_text("assertion")
    frozen=tmp_path/"candidate-crash.log";frozen.write_bytes(runtime.read_bytes())
    write(tmp_path/"source.json",{"source_sha256":"source"})
    write(tmp_path/"crash-probes.json",{"source_sha256":"source","probes":{
        "call":{"log":"candidate-crash.log","log_sha256":digest(frozen),"runtime_log":"editor.log"}}})
    runtime.write_text("assertion\nlate shutdown trace")
    assert "call" in checked_crashes(tmp_path)
