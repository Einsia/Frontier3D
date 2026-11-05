"""Reject identifier/path escapes before model calls or campaign writes."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark.engine import verify_generated
from src.generator.client import GeneratorConfig,build_generation_command

ROOT=Path(__file__).resolve().parents[1]


def test_model_override_selects_target_harness_binary_and_effort(tmp_path):
    env=tmp_path/'config.env'
    env.write_text('OPENAI_API_KEY=offline-fixture\nOPENAI_BASE_URL=https://provider.invalid/v1\nOPENAI_MODEL=gpt-6-astra\nGENERATOR_CODEX_BIN=/fixture/codex\nGENERATOR_DSH_BIN=/fixture/dsh\n')
    cfg=GeneratorConfig.from_env(env,model='deepseek-v4.1-flash')
    command=build_generation_command(cfg,tmp_path/'bundle.json',tmp_path)
    assert cfg.harness=='deepseek-harness' and cfg.reasoning_effort=='max'
    assert command[command.index('--native-bin')+1]=='/fixture/dsh'
    qwen=GeneratorConfig.from_env(env,model='qwen3.8-max')
    assert qwen.harness=='claude-code' and qwen.reasoning_effort=='xhigh'


@pytest.mark.parametrize('model',['../escaped','/tmp/absolute-model','provider/../../escaped','./model','model\\name'])
@pytest.mark.parametrize('entry',['main','l3'])
def test_cli_rejects_path_models_before_creating_output(tmp_path,model,entry):
    output=tmp_path/'untouched'
    if entry=='main':
        command=[sys.executable,'-m','benchmark','generate','--model',model,'--task','L1/Text2Code/task_L1_Text2Code_001','--env-file',str(tmp_path/'missing.env'),'--output',str(output)]
    else:
        command=[sys.executable,str(ROOT/'harness/L3/release/run.py'),'init','--model',model,'--task','l3-e01','--campaign',str(output)]
    result=subprocess.run(command,cwd=ROOT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    assert result.returncode!=0 and not output.exists()


@pytest.mark.parametrize('name',['../outside.txt','/tmp/absolute.txt','input\\outside.txt','link.txt'])
def test_resume_source_manifest_rejects_escape_and_symlink(tmp_path,name):
    source=tmp_path/'source';source.mkdir()
    outside=tmp_path/'outside.txt';outside.write_text('offline canary')
    (source/'link.txt').symlink_to(outside)
    generation=tmp_path/'generation';generation.mkdir();history=generation/'generation.json';history.write_text('{}')
    result={'submission':str(source),'generation_run':str(generation),
            'source_sha256':{name:hashlib.sha256(outside.read_bytes()).hexdigest()},
            'generation_sha256':hashlib.sha256(history.read_bytes()).hexdigest()}
    with pytest.raises(ValueError):verify_generated(result)


def test_resume_accepts_regular_bound_files(tmp_path):
    source=tmp_path/'source';source.mkdir();code=source/'solution.py';code.write_text('import bpy\n')
    history=tmp_path/'generation.json';history.write_text('{}')
    verify_generated({'submission':str(source),'generation_run':str(tmp_path),
                      'source_sha256':{'solution.py':hashlib.sha256(code.read_bytes()).hexdigest()},
                      'generation_sha256':hashlib.sha256(history.read_bytes()).hexdigest()})
