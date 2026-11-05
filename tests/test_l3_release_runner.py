"""Fresh L3 campaign and host-verifier wiring without model or UE calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / 'harness/L3/release'

def run(*args, check=True):
    return subprocess.run([sys.executable, str(RELEASE/'run.py'), *map(str,args)],
                          cwd=ROOT, capture_output=True, text=True, check=check)

def test_fresh_campaign_and_pending_export(tmp_path):
    campaign=tmp_path/'campaign'
    run('init','--campaign',campaign)
    manifest=json.loads((campaign/'manifest.json').read_text())
    assert len(manifest['rows'])==15
    assert all(r['status']=='queued' and r['enabled'] and r['reuse_source'] is None for r in manifest['rows'])
    assert all(Path(r['task_path']).is_dir() for r in manifest['rows'])
    assert len(list((campaign/'evaluations/quality-v5-specs').glob('*/spec.json')))==15
    assert json.loads((campaign/'settings.json').read_text())['scoring_protocol']=='l3-perceptual-quality-v5'
    run('export','--campaign',campaign)
    import csv
    rows=list(csv.DictReader((campaign/'scores.csv').open()))
    assert len(rows)==15 and all(r['status']=='pending' and r['score_100']=='' for r in rows)
    assert run('init','--campaign',campaign,check=False).returncode!=0

def test_unknown_task_rejected(tmp_path):
    assert run('init','--campaign',tmp_path/'bad','--task','unknown',check=False).returncode!=0


def test_development_build_reuses_existing_engine_binaries(tmp_path):
    import os
    engine=tmp_path/'engine'
    build=engine/'Engine/Build/BatchFiles/Linux/Build.sh'
    build.parent.mkdir(parents=True)
    build.write_text('#!/bin/sh\nfor arg do if [ "$arg" = "-UsePrecompiled" ]; then echo precompiled-engine; exit 0; fi; done\nexit 42\n')
    build.chmod(0o700)
    project=tmp_path/'project';(project/'Source').mkdir(parents=True)
    (project/'Smoke.uproject').write_text('{}')
    (project/'Source/SmokeEditor.Target.cs').write_text('// Target discovery fixture\n')
    output=tmp_path/'build'
    env={**os.environ,'UE5_ROOT':str(engine),'XDG_RUNTIME_DIR':str(tmp_path/'runtime')}
    result=subprocess.run([sys.executable,str(RELEASE/'codebase/ue5/agent_environment/ue.py'),
                           'build',str(project),'--output',str(output)],env=env,
                          text=True,capture_output=True,check=False)
    assert result.returncode==0,result.stderr
    assert (output/'build.log').read_text().strip()=='precompiled-engine'


def test_engine_preflight_requires_renderer_and_build_toolchain(tmp_path):
    from harness.L3.release.engine_checks import REQUIRED,engine_errors
    for name,executable in REQUIRED.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        if executable:p.chmod(0o700)
    version=tmp_path/'Engine/Build/Build.version'
    version.write_text(json.dumps(dict(MajorVersion=5,MinorVersion=8,PatchVersion=3)))
    assert engine_errors(tmp_path,'test engine')==[]
    (tmp_path/'Engine/Binaries/Linux/UnrealEditor').unlink()
    errors=engine_errors(tmp_path,'test engine')
    assert len(errors)==1 and 'Engine/Binaries/Linux/UnrealEditor' in errors[0]
    (tmp_path/'Engine/Binaries/DotNET/UnrealBuildTool/UnrealBuildTool.dll').unlink()
    assert len(engine_errors(tmp_path,'test engine'))==2

def test_evaluate_passes_fresh_output_and_frozen_identity(tmp_path, monkeypatch):
    campaign=tmp_path/'campaign'
    run('init','--campaign',campaign,'--task','l3-e01')
    spec=importlib.util.spec_from_file_location('l3_public_runner',RELEASE/'run.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    monkeypatch.setattr(module.subprocess,'run',lambda cmd,**kw:calls.append((cmd,kw)))
    from argparse import Namespace
    module.evaluate(Namespace(campaign=campaign,task=None,engine=tmp_path/'trusted-engine',gpu=2,provider=tmp_path/'provider.json',resume=True))
    assert len(calls)==1
    cmd,options=calls[0]
    assert options['check']
    assert cmd[cmd.index('--task')+1]=='l3-e01'
    assert cmd[cmd.index('--model')+1]=='gpt-6.1-sol'
    assert cmd[cmd.index('--effort')+1]=='max'
    assert cmd[cmd.index('--gpu')+1]=='2'
    assert '--resume' in cmd
    assert Path(cmd[cmd.index('--output')+1]).is_relative_to(campaign/'evaluations/fresh')


@pytest.mark.parametrize('tamper',['none','source','verifier','evidence','manifest','empty'])
def test_resume_requires_unchanged_collected_source_and_evidence(tmp_path,tamper):
    script=r'''
import sys,json,hashlib
from pathlib import Path
release,base=map(Path,sys.argv[1:3]);tamper=sys.argv[3]
sys.path[:0]=[str(release),str(release/'codebase')]
import verify
from harness.L3.MinecraftVillage.protocol import tree_digest
trial=base/'trial';project=trial/'workspace/project';project.mkdir(parents=True)
(project/'scene.cpp').write_text('// fixture')
manifest=trial/'submission-manifest.json';manifest.write_text('{}')
runtime=base/'runtime';trusted=runtime/'workspace/project';trusted.mkdir(parents=True)
(trusted/'observer.cpp').write_text('// trusted fixture')
image=runtime/'workspace/episodes/views/view.png';image.parent.mkdir(parents=True);image.write_bytes(b'fixed-render-evidence')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
verify.write(runtime/'source.json',{'trial':str(trial),'manifest_sha256':sha(manifest),
 'source_sha256':tree_digest(project),'verification_source_sha256':tree_digest(trusted)})
verify.write(runtime/'run.json',{'status':'collected','evidence_sha256':{str(image.relative_to(runtime)):sha(image)}})
if tamper=='source':(project/'scene.cpp').write_text('// changed')
elif tamper=='verifier':(trusted/'observer.cpp').write_text('// changed')
elif tamper=='evidence':image.write_bytes(b'changed')
elif tamper=='manifest':manifest.write_text('{"changed":true}')
elif tamper=='empty':verify.write(runtime/'run.json',{'status':'collected','evidence_sha256':{}})
try:verify.validate_collected(runtime,trial)
except ValueError:
 assert tamper!='none'
else:assert tamper=='none'
'''
    subprocess.run([sys.executable,'-c',script,str(RELEASE),str(tmp_path),tamper],cwd=ROOT,check=True)

@pytest.mark.parametrize("task_key",["l3-e01","l3-g01"])
def test_host_verifier_collects_and_scores_with_native_task_identity(tmp_path,task_key):
    # Run in a fresh interpreter so the nested L3 source layout is exercised.
    trial=tmp_path/'trial';trial.mkdir();(trial/'submission-manifest.json').write_text('{"harness":"codex"}')
    engine=tmp_path/'engine';binary=engine/'Engine/Binaries/Linux/UnrealEditor-Cmd'
    binary.parent.mkdir(parents=True);binary.write_text('fixture')
    provider=tmp_path/'provider.json';provider.write_text('{}')
    output=tmp_path/'evaluation';reward=tmp_path/'reward.txt'
    script = r"""
import json,sys
from pathlib import Path
from unittest.mock import patch
release=Path(sys.argv[1]);sys.path[:0]=[str(release),str(release/'codebase')]
import verify
import harness.L3.Suite.submission_binding as binding
import harness.L3.Suite.policy as policy
trial,engine,provider,output,reward=map(Path,sys.argv[2:7])
key=sys.argv[7];native=next(p.parent for p in (release/'codebase/tasks/L3').glob('*/task.json') if json.loads(p.read_text()).get('key')==key and json.loads(p.read_text()).get('execution_status')=='generation_ready');events=[]
def validate(*args):events.append(args)
def execute(cmd,**kwargs):
 if str(release/'score_one.py') in cmd:
  row=json.loads((output/'row.json').read_text())
  assert row['task_path']==str(native)
  assert row['harness']=='codex'
  assert row['task_key']==key and row['model']=='gpt-6.1-sol' and row['effort']=='max'
  report=output/'review-v5'/key/'gpt-6.1-sol'/'summary.json'
  verify.write(report,{'protocol':'l3-perceptual-quality-v5','status':'measured','missing_axes':[],'score_100':73.5})
 else:
  assert '--collect-only' in cmd and '--key' in cmd
sys.argv=['verify','--task',key,'--trial',str(trial),'--engine',str(engine),'--provider',str(provider),'--output',str(output),'--reward',str(reward),'--model','gpt-6.1-sol','--effort','max']
with patch.object(binding,'validate_submission',side_effect=validate),patch.object(verify.subprocess,'run',side_effect=execute):
 verify.main()
assert len(events)==2 and all(args[1:]==(key,'gpt-6.1-sol','max') for args in events)
assert float(reward.read_text())==.735
assert json.loads((output/'verifier-result.json').read_text())['status']=='measured'
"""
    subprocess.run([sys.executable,'-c',script,str(RELEASE),str(trial),str(engine),str(provider),str(output),str(reward),task_key],check=True,cwd=ROOT)


def test_continuous_release_id_resolves_to_frozen_harbor_key(tmp_path):
    campaign=tmp_path/'campaign'
    run('init','--campaign',campaign,'--task','L3/Unified/task_L3_Unified_007')
    rows=json.loads((campaign/'manifest.json').read_text())['rows']
    assert len(rows)==1 and rows[0]['task_key']=='l3-g01'
    listing=run('list').stdout
    assert 'L3/Image2Environment/task_L3_Image2Environment_005\tl3-g01' in listing
