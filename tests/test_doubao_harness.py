"""Doubao/Qwen native Claude Code routes; no model or UE service is contacted."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from src.generator.client import GeneratorConfig, build_generation_command
from src.generator.harnesses import generator_harness

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = {
    "protocol": "l1-submission-bundle-v1", "entrypoint": "solution.py",
    "files": [{"path": "solution.py", "encoding": "utf-8", "content": "import bpy\n"},
              {"path": "README.md", "encoding": "utf-8", "content": "Diagnostic fixture"}],
    "runtime": "Blender Python", "dependencies": ["bpy"], "run_instructions": "Run solution.py",
}


def config(model="doubao-seed-evolving", **kwargs):
    return GeneratorConfig(api_key="fixture-generator-key", base_url="https://provider.invalid/custom/v1",
                           model=model, reasoning_effort="max", **kwargs)


def fake_claude(tmp_path, *, failure=False):
    capture = tmp_path / "native-capture.json"
    file = tmp_path / "fake-claude"
    script = f'''#!{sys.executable}
import json,os,sys
from pathlib import Path
Path({str(capture)!r}).write_text(json.dumps({{
 'argv':sys.argv,'stdin':sys.stdin.read(),'api_key':os.environ.get('ANTHROPIC_API_KEY'),
 'base_url':os.environ.get('ANTHROPIC_BASE_URL'),'auth_token':os.environ.get('ANTHROPIC_AUTH_TOKEN'),
 'capabilities':os.environ.get('ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES')}}))
print(json.dumps({{'type':'result','is_error':{failure!r},'session_id':'fixture-native-session',
 'structured_output':{BUNDLE!r},'usage':{{'input_tokens':7,'output_tokens':3,
 'cache_read_input_tokens':5,'cache_creation_input_tokens':2}}}}))
'''
    file.write_text(script)
    file.chmod(0o700)
    return file, capture


@pytest.mark.parametrize("model", ["doubao-seed-evolving", "Doubao-test-alias", "qwen3.8-max", "Qwen-test-alias"])
def test_doubao_family_selects_claude_while_gpt_keeps_codex(model):
    assert generator_harness(model) == "claude-code"
    gpt = GeneratorConfig(api_key="fixture", base_url="https://provider.invalid/v1", model="gpt-6-luna")
    assert gpt.harness == "codex"


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("model", ["doubao-seed-evolving", "qwen3.8-max"])
def test_host_adapter_uses_configured_auth_schema_images_and_preserves_failure_usage(tmp_path, failure, model):
    binary, capture = fake_claude(tmp_path, failure=failure)
    workspace = tmp_path / "public";workspace.mkdir()
    image = workspace / "reference.png";image.write_bytes(b"image fixture")
    schema = tmp_path / "schema.json";schema.write_text('{"type":"object"}')
    output = tmp_path / "bundle.json"
    command = build_generation_command(config(model=model, claude_binary=str(binary)), output, workspace,
                                       image_paths=[image], output_schema=schema)
    assert "fixture-generator-key" not in " ".join(command)
    cp = subprocess.run(command, input="Read the task and submit a bundle", text=True,
                        cwd=workspace, env={**os.environ, "CODEX_API_KEY": "fixture-generator-key",
                                            "ANTHROPIC_AUTH_TOKEN": "stale-token"},
                        capture_output=True, check=False)
    assert (cp.returncode != 0) == failure
    native = json.loads(capture.read_text());args = native["argv"]
    assert native["api_key"] == "fixture-generator-key" and native["auth_token"] is None
    assert native["base_url"] == "https://provider.invalid/custom"
    assert args[args.index("--model") + 1] == model
    assert args[args.index("--effort") + 1] == "max"
    assert json.loads(args[args.index("--json-schema") + 1]) == {"type": "object"}
    assert str(image) in native["stdin"] and "Read tool" in native["stdin"]
    assert "Bash" not in args[args.index("--tools") + 1]
    from src.run_usage import parse_events
    result = parse_events(cp.stdout)
    assert result["usage"]["input_tokens"] == 14 and result["usage"]["total_tokens"] == 17
    assert result["session_ids"] == ["fixture-native-session"]
    if failure:
        assert not output.exists()
    else:
        assert json.loads(output.read_text()) == BUNDLE


def test_docker_adapter_mounts_schema_images_and_immutable_snapshot_without_key(tmp_path):
    workspace = tmp_path / "public";workspace.mkdir()
    output = tmp_path / "output/bundle.json";output.parent.mkdir()
    image = tmp_path / "outside.png";image.write_bytes(b"fixture")
    schema = tmp_path / "schema.json";schema.write_text('{}')
    session = tmp_path / "session";session.mkdir()
    cfg = config(runtime="docker")
    command = build_generation_command(cfg, output, workspace, image_paths=[image],
                                       output_schema=schema, session_root=session)
    assert command[:4] == ["docker", "run", "--rm", "-i"]
    assert "3dbench-claude:2.1.268" in command and "3dbench-codex:0.163.0" not in command
    assert "fixture-generator-key" not in " ".join(command)
    assert f"type=bind,src={workspace},dst=/workspace,readonly" in command
    assert f"type=bind,src={schema},dst=/schema.json,readonly" in command
    assert any(str(image) in a and a.endswith(',readonly') for a in command)
    assert "/reference_images/reference_000.png" in command and "--allow-shell" in command
    receipt = json.loads((session / "harness-adapter.json").read_text())
    assert receipt["harness"] == "claude-code"
    assert receipt["sha256"] == hashlib.sha256((session / "harness-adapter.py").read_bytes()).hexdigest()
    (session / "harness-adapter.py").chmod(0o600)
    (session / "harness-adapter.py").write_text("# changed adapter")
    with pytest.raises(ValueError, match="source changed"):
        build_generation_command(cfg, output, workspace, session_root=session)


@pytest.mark.parametrize("level", [1, 2])
@pytest.mark.parametrize("model", ["doubao-seed-evolving", "qwen3.8-max"])
def test_l1_l2_bundle_pipeline_records_claude_and_decodes_real_adapter_output(tmp_path, level, model):
    from orchestrator.generator import generate
    from orchestrator.tasks import Task
    binary, _ = fake_claude(tmp_path)
    root = tmp_path / "task";root.mkdir();(root/'environment/input').mkdir(parents=True)
    (root/'instruction.md').write_text('Create a cube')
    (root/'environment/input/reference.png').write_bytes(b'fixture')
    task = Task(root, dict(id=f'L{level}/fixture', level=level,
                          category='Text2Code' if level==1 else 'Brief2Scene',
                          instruction='instruction.md', environment='environment',
                          environment_files=['input/reference.png']))
    run = tmp_path / 'run';run.mkdir()
    source, history = generate(task, run, deadline=time.monotonic()+30, timeout=20, attempts=1,
                               runtime='local',config=config(model=model, claude_binary=str(binary)))
    assert (source/'solution.py').read_text() == 'import bpy\n'
    assert history[0]['status']=='success' and history[0]['harness']=='claude-code'
    assert history[0]['tokens']==17 and history[0]['harness_adapter']['harness']=='claude-code'
    assert json.loads((run/'generation_context.json').read_text())['generator_harness']=='claude-code'


@pytest.mark.parametrize("model", ["doubao-seed-evolving", "qwen3.8-max"])
def test_l3_public_init_selects_claude_and_rejects_explicit_doubao_codex(tmp_path, model):
    runner=ROOT/'harness/L3/release/run.py'
    campaign=tmp_path/'campaign'
    command=[sys.executable,str(runner),'init','--campaign',str(campaign),
             '--model',model,'--task','l3-e01']
    cp=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,check=False)
    assert cp.returncode==0,cp.stderr
    rows=json.loads((campaign/'manifest.json').read_text())['rows']
    assert len(rows)==1 and rows[0]['harness']=='claude'
    cp=subprocess.run([*command[:3], '--campaign',str(tmp_path/'wrong'),'--model',model,
                       '--harness','codex'],cwd=ROOT,text=True,capture_output=True,check=False)
    assert cp.returncode!=0 and 'requires Claude Code' in cp.stderr


@pytest.mark.parametrize("model,effort", [("doubao-seed-evolving", "max"), ("qwen3.8-max", "xhigh")])
def test_l3_native_claude_preserves_doubao_identity_and_max_capabilities(tmp_path, model, effort):
    # Native module is imported in an isolated interpreter to avoid root/nested package collisions.
    source = ROOT/'harness/L3/release/codebase/tools/l3_native_agent.py'
    code = r'''
import importlib.util,sys
from argparse import Namespace
from pathlib import Path
spec=importlib.util.spec_from_file_location('native',sys.argv[1]);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.CLOSEOUT_CONTROL=Path(sys.argv[2])/'no-closeout'
module.Path=lambda value:Path(sys.argv[2])/value.lstrip('/')
model,effort=sys.argv[3:5]
args=Namespace(harness='claude',model=model,effort=effort,image=[])
command,prompt,env=module.command_for(args,'fixture')
assert command[command.index('--model')+1]==model
assert command[command.index('--effort')+1]==effort
assert env['ANTHROPIC_CUSTOM_MODEL_OPTION']==model
assert 'max_effort' in env['ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES']
assert env['ANTHROPIC_API_KEY']=='local-bridge-no-secret'
args.harness='codex'
try:module.command_for(args,'fixture')
except ValueError as error:assert 'requires Claude Code' in str(error)
else:raise AssertionError('Direct native invocation silently routed Doubao through Codex')
'''
    subprocess.run([sys.executable,'-c',code,str(source),str(tmp_path),model,effort],check=True,cwd=ROOT)


def test_l3_native_doctor_accepts_claude_only_installation(tmp_path):
    code = r'''
import importlib.util,json,os,sys
from argparse import Namespace
from pathlib import Path
release=Path(sys.argv[1]);root=Path(sys.argv[2]);sys.path.insert(0,str(release))
spec=importlib.util.spec_from_file_location('native_doctor',release/'doctor.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.verify_resources=lambda:{}
module.engine_errors=lambda *a:[]
module.metadata=lambda:{}
module.shutil.which=lambda value:'/fixture/'+value
module.subprocess.run=lambda *a,**kw:Namespace(returncode=0)
native=root/'node_modules';package=native/'@anthropic-ai/claude-code/package.json';package.parent.mkdir(parents=True)
package.write_text(json.dumps({'version':'2.1.268'}))
binary=native/'.bin/claude';binary.parent.mkdir();binary.write_text('#!/bin/sh\nexit 0\n');binary.chmod(0o700)
original=root/'original';original.mkdir();engine=root/'candidate';engine.mkdir();assets=root/'assets';assets.mkdir()
providers=root/'providers';providers.mkdir();provider=providers/'openai.json';provider.write_text(json.dumps({'base_url':'https://provider.invalid','api_key':'offline-fixture'}))
os.environ.update(L3_UE_ROOT=str(original),L3_NATIVE_CLI=str(native),L3_PROVIDER_DIR=str(providers),L3_MATRIX_JUDGE_PROVIDER=str(provider),L3_ASSET_ROOT=str(assets),L3_UE_IMAGE='fixture-l3',L3_GENERATOR_HARNESS='claude')
args=Namespace(resources_only=False,engine=engine,provider=None,verify_assets=False)
result=module.check(args)
assert result['errors']==[],result
assert result['generator_harness']=='claude'
os.environ['L3_GENERATOR_HARNESS']='codex'
result=module.check(args)
assert any('@openai/codex/package.json' in error for error in result['errors']),result
assert not any('@anthropic-ai' in error for error in result['errors']),result
'''
    subprocess.run([sys.executable, '-c', code, str(ROOT/'harness/L3/release'), str(tmp_path)], check=True, cwd=ROOT)


def test_main_l3_doctor_passes_model_harness_in_private_child_environment(tmp_path, monkeypatch):
    from argparse import Namespace
    from benchmark import l3

    captured = {}
    monkeypatch.setattr(l3, 'runtime', lambda args: Namespace(candidate=None, evaluator=None, gpu=0))
    monkeypatch.setattr(l3, 'environment', lambda root: {'L3_NATIVE_CLI': str(tmp_path)})
    monkeypatch.setattr(l3, 'judge_settings', lambda: {'OPENAI_MODEL': 'doubao-seed-evolving'})
    def run(command, **kwargs):
        captured.update(kwargs['env'])
        return Namespace(returncode=0, stdout=json.dumps({'errors': []}))
    monkeypatch.setattr(l3.subprocess, 'run', run)
    original = os.environ.get('L3_GENERATOR_HARNESS')
    l3.doctor(Namespace(resources_only=False, verify_assets=False))
    assert captured['L3_GENERATOR_HARNESS'] == 'claude'
    assert os.environ.get('L3_GENERATOR_HARNESS') == original
