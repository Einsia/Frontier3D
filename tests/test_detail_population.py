"""Formal native detail cannot reuse or publish a diagnostic subset."""
import json
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import measure_effort_legacy_detail as measurement
from tools.evaluate_linear_candidate import pin
from src.evaluator.legacy_detail import require_full_population


@pytest.fixture(params=[1,2])
def campaign(tmp_path,monkeypatch,request):
    def write(path,data):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(data))
    task=('L1/Text2Code/task_L1_Text2Code_001' if request.param==1
          else 'L2/Brief2Scene/task_L2_Brief2Scene_001')
    population=[seed+'/'+fmt for seed in ['primary','seed-0','seed-1','seed-2']
                for fmt in (['native','glb'] if request.param==1 else ['native'])]
    run=tmp_path/'run'
    write(run/'run.json',{})
    write(tmp_path/'fixture/batch.json',{'cases':[{'task_id':task,'status':'completed','run_dir':str(run)}]})
    write(tmp_path/'campaign.json',{'frozen':str(tmp_path),'provider_transport':'https://offline.invalid'})
    write(tmp_path/'rule/plan.json',{})
    write(tmp_path/'rule/judge_spec.json',{})
    write(tmp_path/'linear_config'/task/'rule.json',{'reference_images':{}})
    plan={'measurements':[{'id':'detail','method':'visual_coverage_deviation','weight':1}]}
    recipe={'criteria':plan['measurements'],'criterion_ids':['detail'],
            'source_plan':pin(tmp_path/'rule/plan.json')}
    binding={'run':pin(run/'run.json'),'plan':recipe['source_plan'],
             'spec':pin(tmp_path/'rule/judge_spec.json'),'variants':population}
    monkeypatch.setattr(measurement,'tested_model',lambda root:'fixture')
    monkeypatch.setattr(measurement,'contract',lambda *a:(recipe,plan,{},population))
    folder=tmp_path/'detail'
    folder.mkdir()
    return tmp_path,task,population,binding,folder,write


def test_formal_measurement_ignores_old_variant_limit_and_measures_all(campaign,monkeypatch):
    root,task,population,binding,folder,write=campaign
    monkeypatch.setenv('LEGACY_DETAIL_VARIANT_LIMIT','2')
    monkeypatch.setattr(measurement,'artifact_variants',lambda *a:{})
    monkeypatch.setattr(measurement,'validate_published_references',lambda *a:None)
    monkeypatch.setattr(measurement,'judge_key',lambda:'offline-unused')
    monkeypatch.setattr(measurement,'judge_model',lambda:'gpt-6-astra')
    monkeypatch.setattr(measurement.JudgeConfig,'from_env',lambda *a:measurement.JudgeConfig(model='gpt-6-astra',api_key='offline-unused'))
    monkeypatch.setitem(sys.modules,'tools.experiment_view_policy',
                        SimpleNamespace(load_views=lambda *a:({},None)))
    called=[]
    class OfflinePool:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def submit(self,fn,variant):
            called.append(variant)
            pointer_path=folder/'judges'/variant/'run.json'
            write(pointer_path,{'status':'scored','criterion_scores':{'detail':.2 if variant==population[-1] else .8}})
            future=Future()
            future.set_result((variant,{'detail':.2 if variant==population[-1] else .8},pin(pointer_path),{},None))
            return future
    monkeypatch.setattr(measurement,'ThreadPoolExecutor',OfflinePool)
    result=measurement._measure(root,task,folder)
    assert called==population and result['measured_variants']==population
    assert result['required_variants']==population and result['score']==.2
    assert result['selected_variant']==population[-1]


@pytest.mark.parametrize('metadata',[True,False])
def test_old_subset_cache_is_rejected_even_without_population_metadata(campaign,metadata):
    root,task,population,binding,folder,write=campaign
    cached={'status':'measured','source_bindings':binding,
            'judge_runs':{v:{} for v in population[:2]}}
    if metadata:
        cached.update(required_variants=population,measured_variants=population[:2])
    write(folder/'detail.json',cached)
    with pytest.raises(ValueError,match='Complete frozen detail population'):
        measurement._measure(root,task,folder)


def test_formal_population_accepts_bound_preparation_zeros_and_rejects_screening():
    population=['primary/native','primary/glb']
    detail={'status':'measured','judge_runs':{'primary/native':{}},
            'preparation_failures':{'primary/glb':{}}}
    require_full_population(detail,population)
    with pytest.raises(ValueError,match='Complete frozen detail population'):
        require_full_population({**detail,'status':'screening'},population)


def test_native_finalizer_rejects_archived_subset_before_publishing(campaign,monkeypatch):
    from tools import finalize_effort_legacy_case as finalizer
    import tools.recover_l1_strict_axes as recovery
    root,task,population,binding,folder,write=campaign
    monkeypatch.setattr(finalizer,'tested_model',lambda root:'fixture')
    monkeypatch.setattr(recovery,'verified_baseline_path',lambda path:path)
    write(root/'legacy_baseline/fixture/cases'/Path(task).name/'report.json',
          {'task_id':task,'source_run_dir':str(root/'run'),'S_core':.5,'score_valid':True})
    judge=folder/'judge.json'
    write(judge,{'status':'scored'})
    write(root/'legacy_detail/fixture'/Path(task).name/'detail.json',
          {'status':'measured','source_bindings':binding,'required_variants':population,
           'measured_variants':population[:2],'judge_runs':{v:pin(judge) for v in population[:2]}})
    with pytest.raises(ValueError,match='Complete frozen detail population'):
        finalizer.finalize(root,task)
    assert not (root/'main_results').exists()


def test_extension_finalizer_rejects_screening_even_if_all_judgments_present():
    from tools.finalize_effort_addition import validate_detail
    with pytest.raises(ValueError,match='Complete frozen detail population'):
        validate_detail({'detail_variants':['primary/native']},{},
                        {'status':'screening','judge_runs':{'primary/native':{}}})
