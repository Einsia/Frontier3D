"""Source-only diagnostic invoker; not an equipped Harbor benchmark trial."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, time, tomllib
from pathlib import Path
from harness.common.codex_invoker import run_once

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / 'tasks/L3/MinecraftVillage'

def generate(output: Path, timeout: float = 1800, model: str | None = None, *, source_only: bool = False) -> dict:
    if not source_only:
        raise RuntimeError('This launcher has no engine/preview environment and cannot run a formal L3 trial. '
                           'Use an equipped Harbor environment; --source-only explicitly opts into a non-benchmark diagnostic.')
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'workspace'
    workspace.mkdir()
    manifest = tomllib.loads((TASK/'task.toml').read_text())
    from src.generator.task_adapter import load_benchmark_task
    task=load_benchmark_task(TASK)
    task.validate_materialized_assets()
    task.stage_environment(workspace)
    prompt = (TASK/'instruction.md').read_text()
    prompt += '\nWork only inside the current workspace. Do not read other submissions or evaluator code. Do not access the network. The engine is unavailable for this attempt. Create the complete project and report unverified build status.\n'
    (workspace/'PROMPT.md').write_text(prompt)
    binary = shutil.which('codex') or str(Path.home()/'.local/bin/codex')
    configpath = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'config.toml'
    config = tomllib.loads(configpath.read_text()) if configpath.exists() else {}
    selected = model or config.get('model')
    command = [binary, 'exec', '--ephemeral', '--ignore-rules', '--skip-git-repo-check',
               '--sandbox', 'workspace-write', '-c', 'approval_policy="never"',
               '-c', 'sandbox_workspace_write.network_access=false', '--json',
               '--image', str(workspace/'input/reference.jpg'),
               '--output-last-message', str(workspace/'model_final.txt')]
    if selected: command += ['--model', selected]
    command += ['-']
    start = time.time()
    result = run_once(command, prompt, cwd=workspace, output_path=workspace/'model_final.txt', timeout=timeout)
    # Logs are local run artifacts, never published with credentials/config files.
    (output/'events.jsonl').write_text(result.stdout)
    (output/'stderr.log').write_text(result.stderr)
    record = {'schema_version':1, 'model':selected, 'generation_status':result.status,
              'error_code':result.error_code, 'started_unix':start, 'elapsed_seconds':result.elapsed_seconds,
              'wall_budget_seconds':timeout, 'attempts':1, 'protocol':'source_only_diagnostic',
              'benchmark_eligible':False, 'environment_engine_available':False,
              'human_feedback':False, 'compile_status':'not_run_engine_unavailable',
              'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
              'input_sha256':{name:hashlib.sha256((workspace/name).read_bytes()).hexdigest() for name in manifest['environment_files']},
              'image_sha256':hashlib.sha256((workspace/'input/reference.jpg').read_bytes()).hexdigest(),
              'project_present':len(list((workspace/'project').glob('*.uproject')))==1,
              'score':None}
    if record['project_present']:
        from src.generator.ue5_project import _validate_generated_project
        from .protocol import validate_bindings, read_json, tree_digest
        try:
            _validate_generated_project(workspace/'project')
            validate_bindings(read_json(workspace/'project/bindings.json'))
            record['structure_status']='passed'
            record['source_sha256']=tree_digest(workspace/'project')
        except (ValueError,RuntimeError,FileNotFoundError,KeyError,TypeError) as error:
            record['structure_status']='failed'
            record['structure_error']=str(error)
    (output/'generation.json').write_text(json.dumps(record, indent=2)+'\n')
    return record

if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=float, default=1800); p.add_argument('--model')
    p.add_argument('--source-only', action='store_true', help='Diagnostic only; no engine, preview or benchmark score')
    a=p.parse_args(); print(json.dumps(generate(a.output,a.timeout,a.model,source_only=a.source_only),indent=2))
