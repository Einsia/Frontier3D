"""Model-specific native invocations and effort boundaries; no provider calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from src.generator.client import GeneratorConfig, build_generation_command
from src.generator.harnesses import REGISTRY_PATH, generator_harness, model_effort, native_harness
from harness.common.experiment_policy import validate_options

MODELS=json.loads(REGISTRY_PATH.read_text())['models']


@pytest.mark.parametrize('row',MODELS,ids=lambda row:row['model'])
def test_model_effort_and_harness_are_shared_with_policy_and_native_l3(row):
    from harness.L3.release.run import selected_harness
    from src.generator.harnesses import native_metadata
    assert generator_harness(row['model'])==row['harness_id']
    assert model_effort(row['model'])==row['effort']
    assert selected_harness(row['model'])==native_harness(row['model'])
    assert native_metadata(row['harness_id'])['version']
    values=dict(model=row['model'],effort=row['effort'],attempts=6,generation_timeout=57600,generation_total_timeout=115200,execution_timeout=28800,evaluation_timeout=86400)
    validate_options(values)
    with pytest.raises(ValueError):validate_options({**values,'effort':'medium'})
    with pytest.raises(ValueError):selected_harness(row['model'],'wrong-cli')


BUNDLE={'protocol':'l1-submission-bundle-v1','entrypoint':'solution.py',
        'files':[{'path':'solution.py','encoding':'utf-8','content':'import bpy\n'},
                 {'path':'README.md','encoding':'utf-8','content':'Native fixture'}],
        'runtime':'Blender Python','dependencies':['bpy'],'run_instructions':'Run solution.py'}


def fake_native(tmp_path,model,*,failure=False):
    binary=tmp_path/'native';capture=tmp_path/'invocation.json';harness=generator_harness(model)
    binary.write_text(f'''#!{sys.executable}
import json,sys,os
from pathlib import Path
Path({str(capture)!r}).write_text(json.dumps({{'argv':sys.argv,'stdin':sys.stdin.read(),
 'effort':os.environ.get('KIMI_MODEL_THINKING_EFFORT'), 'gemini_key_set':bool(os.environ.get('GEMINI_API_KEY'))}}))
bundle={BUNDLE!r};text=json.dumps(bundle);harness={harness!r}
if harness=='deepseek-harness':
 print(json.dumps({{'phase':'step_end','usage':{{'inputTokens':7,'outputTokens':3,'cacheReadTokens':5}}}}))
 print(json.dumps({{'type':'final','text':text}}))
elif harness=='kimi-codecli':print(json.dumps({{'role':'assistant','content':text,'usage':{{'input_tokens':7,'output_tokens':3}}}}))
elif harness=='zcode':print(json.dumps({{'response':text,'usage':{{'inputTokens':7,'outputTokens':3}}}}))
elif harness=='gemini-cli':
 print(json.dumps({{'type':'message','role':'assistant','content':text}}))
 print(json.dumps({{'type':'result','status':'error' if {failure!r} else 'success','stats':{{'input_tokens':7,'output_tokens':3}}}}))
sys.exit(1 if {failure!r} else 0)
''');binary.chmod(0o700)
    return binary,capture


@pytest.mark.parametrize('model',['deepseek-v4.1-flash','kimi-k3','glm-5.3-flash','gemini-3.1-pro-preview'])
@pytest.mark.parametrize('level',[1,2])
def test_real_adapter_delivers_bundle_through_l1_l2_pipeline(tmp_path,model,level):
    from orchestrator.generator import generate
    from orchestrator.tasks import Task
    binary,capture=fake_native(tmp_path,model)
    root=tmp_path/'task';root.mkdir();(root/'environment/input').mkdir(parents=True)
    (root/'instruction.md').write_text('Create a cube')
    (root/'environment/input/reference.png').write_bytes(b'fixture')
    task=Task(root,dict(id=f'L{level}/fixture',level=level,category='Text2Code' if level==1 else 'Brief2Scene',
                       instruction='instruction.md',environment='environment',environment_files=['input/reference.png']))
    cfg=GeneratorConfig(api_key='offline-fixture',base_url='https://provider.invalid/v1',model=model,native_binary=str(binary))
    run=tmp_path/'run';run.mkdir()
    source,history=generate(task,run,deadline=time.monotonic()+30,timeout=20,attempts=1,runtime='local',config=cfg)
    assert (source/'solution.py').read_text()=='import bpy\n'
    assert history[0]['status']=='success' and history[0]['harness']==generator_harness(model)
    assert history[0]['tokens']==10
    metadata=json.loads((run/'generation_context.json').read_text())
    assert metadata['generator_harness']==generator_harness(model)
    call=json.loads(capture.read_text());args=call['argv']
    assert any(model in value for value in args) or generator_harness(model)=='deepseek-harness'
    if model.startswith('glm'):assert args[args.index('--effort')+1]=='max'
    if model.startswith('gemini'):assert call['gemini_key_set']


@pytest.mark.parametrize('model',['deepseek-v4.1-flash','kimi-k3','glm-5.3-flash','gemini-3.1-pro-preview'])
def test_native_failure_retains_usage_but_no_bundle(tmp_path,model):
    from src.run_usage import parse_events
    binary,_=fake_native(tmp_path,model,failure=True);output=tmp_path/'bundle.json'
    cfg=GeneratorConfig(api_key='offline-fixture',base_url='https://provider.invalid/v1',model=model,native_binary=str(binary))
    command=build_generation_command(cfg,output,tmp_path)
    result=subprocess.run(command,input='fixture',cwd=tmp_path,env={**os.environ,'CODEX_API_KEY':'offline-fixture'},text=True,capture_output=True)
    assert result.returncode and not output.exists()
    assert parse_events(result.stdout)['usage']['total_tokens']==10


@pytest.mark.parametrize('model',['qwen3.8-max','gemini-3.1-pro-preview'])
def test_l3_init_uses_declared_nonmax_effort_without_provider(tmp_path,model):
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'harness/L3/release/run.py'),'init','--model',model,
                           '--task','l3-e01','--campaign',str(tmp_path/'campaign')],cwd=root,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    row=json.loads((tmp_path/'campaign/manifest.json').read_text())['rows'][0]
    assert row['harness']==native_harness(model) and row['effort']==model_effort(model)


@pytest.mark.parametrize('model',['qwen3.8-max','gemini-3.1-pro-preview'])
def test_public_cli_resolves_effort_before_campaign_and_preserves_it_in_export(tmp_path,monkeypatch,model):
    from benchmark import __main__ as cli
    from benchmark import engine
    from benchmark.resources import prepare
    captured={}
    def execute(args,parser,options,output,tasks,rows):
        captured.update(model=args.model,effort=args.effort,options=options)
        return 0
    monkeypatch.setattr(cli,'execute_campaign',execute)
    monkeypatch.setattr(sys,'argv',['benchmark','generate','--model',model,'--all','--level','1','--env-file',str(tmp_path/'unused.env'),'--output',str(tmp_path/'run')])
    assert cli.main()==0
    assert captured['model']==model and captured['effort']==model_effort(model)
    assert captured['options']['effort']==model_effort(model)


def test_native_gemini_gateway_sets_thinking_without_leaking_authentication():
    root=Path(__file__).resolve().parents[1]
    code=r'''
import sys,json,types
from pathlib import Path
sys.path.insert(0,sys.argv[1])
package=types.ModuleType('tools');package.__path__=[str(Path(sys.argv[1])/'tools')];sys.modules['tools']=package
from tools.l3_model_bridge import model_payload,upstream_headers,image_count
from tools.l3_batch_control import MultiUsageParser
route='/v1beta/models/gemini-3.1-pro-preview:streamGenerateContent'
body=model_payload(b'{"contents":[]}',route,{'L3_EXPECTED_MODEL':'gemini-3.1-pro-preview','L3_EXPECTED_EFFORT':'high'})
p=json.loads(body);assert 'model' not in p and p['generationConfig']['thinkingConfig']['thinkingLevel']=='HIGH'
headers=upstream_headers({'x-goog-api-key':'placeholder','Authorization':'Bearer placeholder'},'fixture-key')
assert 'x-goog-api-key' not in headers and headers['authorization']=='Bearer fixture-key'
assert image_count({'inlineData':{'data':'fixture'}})==1
parser=MultiUsageParser();parser.feed(b'data: {"usageMetadata":{"promptTokenCount":20,"candidatesTokenCount":3,"thoughtsTokenCount":2,"totalTokenCount":25}}\n');parser.finish()
assert parser.usage['input_tokens']==20 and parser.usage['output_tokens']==5 and parser.usage['reasoning_output_tokens']==2
'''
    subprocess.run([sys.executable,'-c',code,str(root/'harness/L3/release/codebase')],check=True)
