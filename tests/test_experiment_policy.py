"""Released generation uses one retry owner and one budget across resumes."""
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from dataclasses import replace

import pytest

from harness.common import experiment_policy as policy

ROOT=Path(__file__).resolve().parents[1]

def options(**changes):
    return {'effort':'max','attempts':6,'generation_timeout':policy.GENERATION_TIMEOUT,
            'generation_total_timeout':policy.GENERATION_TOTAL_TIMEOUT,
            'execution_timeout':policy.EXECUTION_TIMEOUT,'evaluation_timeout':policy.EVALUATION_TIMEOUT,
            'runtime':'local','image':'fixture','generator_runtime':'local','tasks_root':str(ROOT/'data/3dbench/tasks'),**changes}

def test_official_effort_and_limits_are_enforced_before_starting_campaign(tmp_path):
    for args in [ ['--effort','medium'],['--attempts','2'],['--generation-total-timeout','115201'],['--generation-timeout','nan'] ]:
        p=subprocess.run([sys.executable,'-m','benchmark','generate','--task','L1/Text2Code/task_L1_Text2Code_001','--output',str(tmp_path/'unused'),*args],cwd=ROOT,capture_output=True,text=True)
        assert p.returncode==2
        assert not (tmp_path/'unused').exists()

def test_all_six_shipped_harnesses_share_generation_policy():
    from harness.common.config import load_config
    files=list((ROOT/'harness').glob('L[12]/*/harness.toml'))
    assert len(files)==6
    for file in files:
        level=int(file.parts[-3][1:]);c=load_config(file,level=level,task_prefix=f'L{level}/')
        assert (c.reasoning_effort,c.timeout_seconds,c.max_total_seconds,c.max_retries)==('max',57600,115200,5)
        assert c.retry_timeout and c.retry_transport_error

def test_generation_budget_is_not_multiplied_by_attempts_or_reset_by_resume(tmp_path,monkeypatch):
    from benchmark import engine
    import orchestrator.generator as gen
    from src.generator.client import GeneratorConfig
    instruction=tmp_path/'instruction.md';instruction.write_text('fixture')
    task=SimpleNamespace(root=tmp_path,manifest={})
    monkeypatch.setattr(engine,'load_task',lambda *a,**k:task)
    monkeypatch.setattr(engine,'task_bindings',lambda task:{})
    monkeypatch.setattr(engine,'blender_path',lambda:tmp_path/'blender')
    monkeypatch.setattr(engine,'env_path',lambda:tmp_path/'private-unused.env')
    monkeypatch.setattr(engine,'generation_validator',lambda *a,**kw:lambda *args:[])
    monkeypatch.setattr(GeneratorConfig,'from_env',lambda *a,**k:GeneratorConfig(api_key='fixture',base_url='https://example.invalid',model='fixture'))
    clock=[100.]
    monkeypatch.setattr(engine.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(engine.time,'time',lambda:clock[0])
    calls=[]
    def generate(task,origin,**kwargs):
        calls.append(kwargs)
        (origin/'generation.json').write_text('{"attempts": [{"status":"process_error"}]}')
        clock[0]+=6
        raise RuntimeError('fixture failed generation')
    monkeypatch.setattr(gen,'generate',generate)
    opt=options(generation_timeout=8,generation_total_timeout=10)
    for _ in range(2):
        with pytest.raises(RuntimeError,match='fixture failed'):
            engine.generate('L1/fixture',tmp_path/'campaign','fixture',opt)
    assert calls[0]['deadline']==110 and calls[0]['resume'] is False
    assert calls[1]['deadline']==110 and calls[1]['resume'] is True
    assert calls[0]['attempts']==6 and calls[0]['config'].reasoning_effort=='max'
    with pytest.raises(TimeoutError,match='budget exhausted'):
        engine.generate('L1/fixture',tmp_path/'campaign','fixture',opt)
    assert len(calls)==2

@pytest.mark.parametrize('failure',['timeout','process_error','mixed'])
def test_legacy_l2_stops_after_six_calls_with_a_single_timeout_tier(tmp_path,monkeypatch,failure):
    import harness.L2.generation as module
    from harness.common.config import load_config
    from src.generator.client import GeneratorConfig
    cfg=load_config(ROOT/'harness/L2/Brief2Scene/harness.toml',level=2,task_prefix='L2/')
    cfg=replace(cfg,backoff_seconds=(0.,))
    monkeypatch.setattr(module,'load_config',lambda *a,**k:cfg)
    monkeypatch.setattr(GeneratorConfig,'from_env',lambda *a,**k:GeneratorConfig(api_key='fixture',base_url='https://example.invalid',model='fixture'))
    monkeypatch.setattr(module,'generation_prompt',lambda *a:'fixture')
    monkeypatch.setattr(module,'generation_command',lambda command,*a,**k:command)
    monkeypatch.setattr(module,'stage_preview',lambda *a,**k:None)
    @contextmanager
    def broker(*a,**k):yield []
    monkeypatch.setattr(module,'preview_broker',broker)
    calls=[]
    def invoke(*args,**kwargs):
        calls.append(kwargs['timeout'])
        status=('success' if len(calls)==1 else 'process_error') if failure=='mixed' else failure
        return SimpleNamespace(status=status,elapsed_seconds=.01,stdout='',stderr='',return_code=1,error_code='fixture')
    monkeypatch.setattr(module,'run_once',invoke)
    def stage(dest):dest.mkdir(parents=True)
    task=SimpleNamespace(environment_files=(),image_files=(),task_id='L2/Brief2Scene',output_slug='fixture',
        validate_materialized_assets=lambda:None,stage_environment=stage)
    result=module.generate(task,ROOT/'harness/L2/Brief2Scene/harness.toml',SimpleNamespace(environment_files=(),threads=1,max_repairs=1),tmp_path/'out',tmp_path/'blender')
    assert len(calls)==result['attempt_count']==6
    assert all(limit<=57600 for limit in calls)

def test_campaign_resume_rejects_different_time_policy(tmp_path,monkeypatch):
    from benchmark import engine
    monkeypatch.setattr(engine,'judge_settings',lambda:{})
    monkeypatch.setattr(engine,'judge_model',lambda:'fixture')
    linear=tmp_path/'linear-source';linear.mkdir()
    monkeypatch.setattr(engine,'resource',lambda key:linear)
    tasks=tmp_path/'task-source';tasks.mkdir()
    root=tmp_path/'campaign'
    initial=options()
    engine.initialize(root,'fixture','max',tasks,initial)
    bound=json.loads((root/'campaign.json').read_text())['generation_policy']
    assert bound['generation_total_timeout']==115200
    changed=options(generation_total_timeout=60000)
    with pytest.raises(ValueError,match='configuration changed'):
        engine.initialize(root,'fixture','max',tasks,changed)

def test_compat_generation_and_evaluation_have_separate_stage_deadlines(tmp_path,monkeypatch):
    import orchestrator.runner as runner
    clock=[100.]
    monkeypatch.setattr(runner.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(runner,'EVALUATION_TIMEOUT',2)
    source=tmp_path/'candidate';source.mkdir()
    (source/'solution.py').write_text('# fixture')
    (source/'README.md').write_text('fixture')
    blender=tmp_path/'blender';blender.write_text('unused')
    captured={}
    def validator(task,run,manifest,**kwargs):
        captured['manifest']=manifest
        return lambda *a:[]
    monkeypatch.setattr(runner,'generation_validator',validator)
    def generate(task,run,**kwargs):
        assert kwargs['deadline']==110
        clock[0]=105
        captured['manifest']['attempts']['baseline']=[{'source_sha256':{'intentionally_mismatched':'fixture'}}]
        return source,[]
    monkeypatch.setattr(runner,'generate',generate)
    result=runner.run_case('L1/Text2Code/task_L1_Text2Code_001',generate_code=True,
        tasks_root=ROOT/'data/3dbench/tasks',output_root=tmp_path/'runs',
        blender=blender,runtime='local',generation_total_timeout=10)
    receipt=json.loads((Path(result['run_dir'])/'run.json').read_text())
    assert receipt['evaluation_deadline_monotonic']==107
    assert receipt['status']!='scored'
