import copy,json,os,subprocess,sys
from pathlib import Path
from tools.publish_l3_multimodel_scores import merge_result
def test_merge_preserves_other_model_scores_and_default():
    task={'model_results':[{'model_id':'gpt-6-astra','report':{'score':.6}}],'result':{'model_id':'gpt-6-astra','report':{'score':.6}},
          'evaluation_results':[{'model_id':'gpt-6-astra','score_100':60}], 'generation_runs':[{'model':'gpt-6-astra','score':60}]}
    old=copy.deepcopy(task)
    result={'model':'gpt-6-sol','score_100':50,'axes':{},'source':{'trial':'/sol'},'missing_axes':[]}
    merge_result(task,result,{})
    assert task['result']==old['result']
    assert task['model_results'][0]==old['model_results'][0]
    assert task['evaluation_results'][0]==old['evaluation_results'][0]
    assert task['model_results'][1]['report']['score']==.5
    merge_result(task,result,{})
    assert len(task['model_results'])==len(task['evaluation_results'])==2
def test_model_evidence_directory_isolated():
    root=Path(__file__).resolve().parents[2]
    for model in ['luna','sol']:
        code="from harness.L3.Suite.policy import MODEL,OUT;print(MODEL);print(OUT)"
        v=subprocess.check_output([sys.executable,'-c',code],cwd=root,env={**os.environ,'L3_EVAL_MODEL':'gpt-6-'+model},text=True)
        assert 'gpt-6-'+model in v and 'suite-'+model+'-v1' in v

def test_text_route_is_translated_but_not_scored_as_claimed_success(tmp_path,monkeypatch):
    from harness.L3.Suite.route_translation import executable_bindings
    from harness.L3.Suite.plans import workflow_plan
    import harness.L3.Suite.vlm as vlm
    (tmp_path/'instruction.md').write_text('Move cargo')
    bindings={'workflow':['pick up cargo'],'entities':{}}
    contract={'entities':[{'id':'cargo','actions':['pick_up']}]}
    monkeypatch.setattr(vlm,'call',lambda *a,**kw:{'steps':[{'op':'invoke','target':'cargo','action':'pick_up','argument':'','target_cm':None,'seconds':0}]})
    result=executable_bindings(bindings,contract,tmp_path,tmp_path)
    assert bindings['workflow']==['pick up cargo']
    plan,metadata=workflow_plan(result,contract)
    assert any(s.get('action')=='pick_up' for s in plan['steps'])
    assert not any('passed' in s for s in plan['steps'])
    _,rejected=workflow_plan(bindings,contract)
    assert len(rejected['rejected'])==1
