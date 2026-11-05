"""Tests for the released entry point, contract relocation and staging boundary."""
from pathlib import Path
import importlib
import json
import hashlib

import pytest

from benchmark.__main__ import inventory
from benchmark.resources import ROOT, prepare
from orchestrator.tasks import load_task


def test_every_released_task_has_a_runtime_route(tmp_path, monkeypatch):
    monkeypatch.setenv("THREEDBENCH_RUN_ROOT",str(tmp_path))
    prepare(tmp_path/"contracts")
    from tools.experiment_additions import contract
    rows=list(inventory())
    assert len(rows)==130
    assert sum(r["route"]=="extension" for r in rows)==46
    for r in rows:
        task=load_task(r["task_id"], require_harness=r["route"]!="extension")
        if r["route"]=="extension":
            _,row,bindings=contract(r["task_id"],ROOT/"data/3dbench/tasks")
            assert row["task_id"]==r["task_id"] and bindings
        elif r["level"]==1:
            from src.evaluator.l1_case import load_case
            load_case(task.root)
        else:
            from src.evaluator.l2_case import load_case
            load_case(task.root)


def test_contracts_relocate_without_old_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("THREEDBENCH_RUN_ROOT",str(tmp_path))
    root=prepare(tmp_path/"relocated"/"contracts")
    checked=0
    def visit(value):
        nonlocal checked
        if isinstance(value,dict):
            if "path" in value and "sha256" in value and isinstance(value["path"],str):
                p=Path(value["path"])
                if p.is_absolute():
                    assert p.is_relative_to(root) or p.is_relative_to(ROOT)
                    assert p.is_file()
                    assert hashlib.sha256(p.read_bytes()).hexdigest()==value["sha256"]
                    checked+=1
            for v in value.values():visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    for p in root.rglob("*.json"):visit(json.loads(p.read_text()))
    assert checked>500
    prepare(root)  # idempotent and binds the same materialized bytes
    p=root/"l1-plans/L1/Text2Code/task_L1_Text2Code_001/alignment.json"
    p.write_text("{}")
    with pytest.raises(ValueError,match="changed"):
        prepare(root)


def test_generator_stages_only_the_public_allowlist(tmp_path):
    task=load_task("L1/Image2Code/task_L1_Image2Code_016",require_harness=False)
    hashes=task.stage(tmp_path/"workspace")
    actual=set(hashes)
    assert actual=={"instruction.md",*task.manifest["environment_files"]}
    assert not any(s.startswith(("solution/","harness/")) for s in actual)


def test_frozen_image_weights_and_no_missing_measurement_imputation():
    from src.evaluator.legacy_detail import replace_connection
    from src.evaluator.legacy_detail_v2 import COMPONENT_RULES
    # Release packaging must not inject the exploratory human-alignment weights.
    policy=json.loads((ROOT/"configs/release/legacy-policy.json").read_text())
    assert policy["replacement_weight"]==.1
    assert len(COMPONENT_RULES)==4


def test_export_does_not_invent_missing_scores(tmp_path):
    from benchmark.export import export_scores
    root=tmp_path/"main_results/model/task";root.mkdir(parents=True)
    (root/"report.json").write_text(json.dumps({"model":"model","task_id":"task","S_core":None}))
    assert export_scores(tmp_path)=={"completed":0,"mean":None}
    (root/"report.json").write_text(json.dumps({"model":"model","task_id":"task","S_core":0.0,"status":"scored"}))
    assert export_scores(tmp_path)=={"completed":1,"mean":0.0}


def test_campaign_lock_excludes_a_second_writer(tmp_path):
    from benchmark.engine import campaign_lock
    with campaign_lock(tmp_path):
        with pytest.raises(ValueError,match="owned"):
            with campaign_lock(tmp_path):
                pytest.fail("second writer acquired the lock")
    with campaign_lock(tmp_path):
        pass


def test_extension_report_is_exported_to_campaign(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from benchmark import engine
    monkeypatch.setenv("THREEDBENCH_RUN_ROOT",str(tmp_path))
    prepare(tmp_path/"contracts")
    from tools import experiment_additions
    task_id="L1/Image2Code/task_L1_Image2Code_016"
    origin=tmp_path/"origin";origin.mkdir()
    (origin/"generation.json").write_text("{}")
    (origin/"solution.py").write_text("# retained source")
    generated={"submission":str(origin),"generation_run":str(origin),
        "source_sha256":{"solution.py":engine.sha256(origin/"solution.py")},
        "generation_sha256":engine.sha256(origin/"generation.json")}
    job=tmp_path/"jobs"/Path(task_id).name
    engine.write_json(job/"generate-result.json",generated)
    engine.write_json(tmp_path/"campaign.json",{"provider_transport":"https://example.invalid/v1"})
    instruction=tmp_path/"instruction.md";instruction.write_text("public")
    monkeypatch.setattr(engine,"load_task",lambda *a,**k:SimpleNamespace(root=tmp_path,manifest={"harness_status":"not_implemented"}))
    source=job/"addition-evaluation/report.json"
    def addition(*a):
        engine.write_json(source,{"S_core":.42,"status":"scored","task_id":task_id,"model":"fixture"})
        return {"report":str(source),"report_sha256":engine.sha256(source)}
    monkeypatch.setattr(experiment_additions,"evaluate",addition)
    assert engine.evaluate(task_id,tmp_path,"fixture",{"tasks_root":str(tmp_path),"effort":"medium"})["S_core"]==.42
    from benchmark.export import export_scores
    assert export_scores(tmp_path)=={"completed":1,"mean":.42}
    (origin/"solution.py").write_text("changed")
    with pytest.raises(ValueError,match="source changed"):
        engine.evaluate(task_id,tmp_path,"fixture",{"tasks_root":str(tmp_path),"effort":"medium"})


def test_export_handles_provider_model_ids_and_nonfinite_scores(tmp_path):
    from benchmark.export import export_scores
    root=tmp_path/"main_results/provider/model/task";root.mkdir(parents=True)
    file=root/"report.json"
    file.write_text(json.dumps({"model":"provider/model","task_id":"task","S_core":.5}))
    assert export_scores(tmp_path)=={"completed":1,"mean":.5}
    for invalid in [float("nan"),float("inf"),True,"0.5"]:
        file.write_text(json.dumps({"model":"provider/model","task_id":"task","S_core":invalid}))
        assert export_scores(tmp_path)=={"completed":0,"mean":None}
