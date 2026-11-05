import json
from PIL import Image
import pytest
from tools.l3_publication_metadata import populate_generation
from tools.publish_l3_multimodel_scores import merge_result
from tools.publish_l3_suite_scores import sha

def test_verified_previews_and_usage_match_scored_model(tmp_path,monkeypatch):
    import tools.l3_publication_metadata as m
    trial=tmp_path/"trial";workspace=trial/"workspace";project=workspace/"project"
    preview=project/"previews/overview.png";preview.parent.mkdir(parents=True)
    Image.new("RGB",(16,8),"green").save(preview)
    capture=workspace/"checks/final/preview.png";capture.parent.mkdir(parents=True);capture.write_bytes(preview.read_bytes())
    (trial/"trial.json").write_text(json.dumps({"model":"gpt-6-luna","elapsed_seconds":125,
        "completion_evidence":{"scene_previews":["checks/final/preview.png"]}}))
    (trial/"submission-manifest.json").write_text(json.dumps({"previews/overview.png":sha(preview)}))
    (trial/"generation-usage.json").write_text('{"reported_tokens":{"output_tokens":20}}')
    monkeypatch.setattr(m,"published_asset",lambda p:{"path":str(p),"sha256":sha(p)})
    task={"key":"l3-e01","generation_runs":[{"model":"gpt-6-luna","images":[]}],
          "model_results":[{"model_id":"gpt-6-luna"}]}
    result={"model":"gpt-6-luna","source":{"trial":str(trial)}}
    populate_generation(task,result,{}, {})
    run=task["generation_runs"][0]
    assert run["seconds"]==125 and run["usage"]["reported_tokens"]["output_tokens"]==20
    assert run["images"][0]["width"]==16 and run["images"][0]["source_sha256"]==sha(preview)
    preview.write_bytes(b"tampered")
    with pytest.raises(ValueError,match="integrity"):populate_generation(task,result,{}, {})

def test_mc_import_has_normal_score_row_and_preserves_reference_images():
    task={"result":{"status":"measured","report":{"score":None}},
          "generation_results":[{"model":"gpt-6-astra","images":[{"url":"/media/original"}]}]}
    result={"model":"gpt-6-astra","score_100":66.6,"axes":{},"source":{"trial":"/trial"},"protocol":"fixed"}
    merge_result(task,result,{})
    assert task["result"]["report"]["score"]==pytest.approx(.666)
    assert task["generation_runs"][0]["images"]==[{"url":"/media/original"}]

def test_current_mc_scores_do_not_include_the_replaced_56_luna(tmp_path):
    task={"key":"l3-g01","result":{},"evaluation_results":[{"model":"gpt-5.6-luna","score_100":35.68}]}
    result={"model":"gpt-6-luna","score_100":30.,"axes":{},"source":{"trial":"/trial"},"protocol":"fixed"}
    merge_result(task,result,{})
    assert len(task["evaluation_results"])==1
    assert task["evaluation_results"][0]["model"]=="gpt-6-luna"
    assert task["archived_evaluation_results"][0]["score_100"]==35.68


def test_csv_download_preserves_other_levels_and_replaces_l3_once():
    import csv,io
    from tools.l3_publication_metadata import score_csv
    existing="batch_id,task_uid,source_task_id,metric,model,status,score_100,native_audit_status\nold,old/L1/x,L1/x,legacy,m,scored,12.345,kept\nb,b/L3/x,L3/x,old,gpt-6-sol,scored,1,\n"
    task={'level':3,'id':'L3/x','batch_id':'b','evaluation_results':[
        {'model':'gpt-6-sol','status':'measured','score_100':42.125,'protocol':'current'},
        {'model':'gpt-6-luna','status':'incomplete','score_100':None}]}
    result=score_csv(existing,[task])
    rows=list(csv.DictReader(io.StringIO(result)))
    assert len(rows)==2 and rows[0]['score_100']=='12.345'
    assert rows[0]['native_audit_status']=='kept'
    assert rows[1]['score_100']=='42.125' and rows[1]['metric']=='current'
    assert score_csv(result,[task])==result

def test_generation_accounting_keeps_cache_subset_and_partial_coverage():
    from tools.l3_publication_metadata import generation_accounting
    raw={'reported_tokens':{'input_tokens':100,'cached_input_tokens':80,'output_tokens':20,'total_tokens':120},
         'requests_started':5,'requests_finished':5,'requests_without_usage':2,'request_elapsed_seconds_sum':37.}
    result=generation_accounting(raw,'gpt-6-luna',50.)
    assert result['generation']['tokens']['total_tokens']==120
    assert result['generation']['usage_calls']==3
    assert result['generation']['usage_complete'] is False
    assert result['generation']['cost_lower_usd'] is None
    assert result['workflow_seconds']==50.
    assert result['by_role_model']['generation'][0]['model']=='gpt-6-luna'
    assert 'judge' not in result
    assert generation_accounting({},'gpt-6-luna',None)=={}


def test_independent_views_bind_to_scored_submission(tmp_path,monkeypatch):
    import tools.publish_l3_suite_scores as pub
    import tools.l3_publication_metadata as m
    monkeypatch.setattr(pub,"ROOT",tmp_path)
    monkeypatch.setattr(m,"published_asset",lambda p:{"path":str(p),"sha256":sha(p)})
    folder=tmp_path/"data/l3/evaluations/suite-luna-v1/l3-e01"
    trial=tmp_path/"trial";trial.mkdir()
    manifest=trial/"submission-manifest.json";manifest.write_text("{}")
    view=folder/"workspace/episodes/views/view_00.png";view.parent.mkdir(parents=True)
    Image.new("RGB",(20,10),"blue").save(view)
    (folder/"views-metadata.json").write_text(json.dumps({"view_00":{"kind":"view","label":"overview"}}))
    source={"source_sha256":"trusted","trial":str(trial),"manifest_sha256":sha(manifest)}
    (folder/"source.json").write_text(json.dumps(source))
    result={"model":"gpt-6-luna","source":source}
    images=m.independent_images("l3-e01",result,{})
    assert images[0]["width"]==20 and images[0]["kind"]=="independent_render"
    wrong={**result,"source":{**source,"source_sha256":"other"}}
    with pytest.raises(ValueError,match="source mismatch"):m.independent_images("l3-e01",wrong,{})
    manifest.write_text('{"modified":true}')
    with pytest.raises(ValueError,match="manifest changed"):m.independent_images("l3-e01",result,{})
