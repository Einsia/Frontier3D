"""Bind unified generation artifacts to the existing addition evaluators."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import json

from pathlib import Path

import shutil

from orchestrator.tasks import sha256, write_json, load_task

ROOT = Path(__file__).resolve().parents[1]

SOURCE = resource('addition_source')

PLANS = resource('addition_config')

ALIASES = {}  # Retired source IDs require the explicit source namespace.

def read(path):
    return json.loads(path.read_text())

def contract(task_id, tasks_root):
    campaign = read(SOURCE/'campaign.json')
    row = next((r for r in campaign['records'] if r['task_id']==task_id), None)
    if row is None:raise ValueError('No released contract for '+task_id)
    bindings={}
    task=load_task(task_id,tasks_root,require_harness=False)
    for name in ['task.toml','instruction.md',*[task.manifest['environment']+'/'+n for n in task.manifest['environment_files']]]:
        bindings['tasks/'+task_id+'/'+name]=sha256(task.root/name)
    return campaign,row,bindings


def prepare(job, folder, result):
    campaign, row, bindings = contract(job['task_id'], Path(job['tasks_root']))
    origin = Path(result['generation_run'])
    manifest = read(origin/'run.json')
    history = read(origin/'generation.json')['attempts']
    if (manifest['task_id'] != job['task_id'] or not (manifest.get('model_call') is True or manifest.get('provided_source') is True)
            or manifest['model'] != job['model'] or (not history and not manifest.get('provided_source'))
            or any(a.get('model') != job['model'] for a in history)):
        raise ValueError('Addition model generation provenance mismatch')
    execution = read(origin/'baseline/attempts.json')[-1]
    if execution['status'] != 'success' or not execution['inputs_unchanged'] or not execution['source_unchanged']:
        raise ValueError('Addition requires a successful public execution')
    for name, digest in result['source_sha256'].items():
        if sha256(Path(result['submission'])/name) != digest:
            raise ValueError('Addition generated source changed')
    output = Path(execution['workspace'])/'output'
    for name, digest in execution['artifact_sha256'].items():
        if sha256(output/name) != digest:
            raise ValueError('Addition generated artifact changed')
    root = folder/'addition-evaluation'
    root.mkdir(exist_ok=True)
    link = root/'tasks'
    if not link.exists():
        link.symlink_to(Path(job['tasks_root']), target_is_directory=True)
    if link.resolve() != Path(job['tasks_root']).resolve():
        raise ValueError('Addition task source changed')
    rule = Path(row['rule'])
    rule_relative = rule.relative_to(SOURCE)
    target = root/rule_relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copyfile(rule, target)
    if sha256(target) != row['rule_sha256']:
        raise ValueError('Addition rules changed')
    bindings[str(rule_relative)] = row['rule_sha256']
    write_json(root/'task_bindings.json', bindings)
    settings = {**campaign, 'models':[job['model']], 'effort':job['effort'], 'blender':str(blender_path()), 'codex':os.environ.get('GENERATOR_CODEX_BIN','codex'), 'execution_timeout':float(os.environ.get('THREEDBENCH_EXECUTION_TIMEOUT','900')), 'project':str(ROOT),
                'records':[{**row, 'task_root':str(root/'tasks'/job['task_id']), 'rule':str(target)}],
                'task_bindings_sha256':sha256(root/'task_bindings.json'),
                'provider_url':job['judge_transport'], 'candidate_count':1}
    config = root/'campaign.json'
    if config.exists() and read(config) != settings:
        raise ValueError('Addition evaluation settings changed')
    write_json(config, settings)
    if not (root/'pricing.json').exists():
        shutil.copyfile(SOURCE/'pricing.json', root/'pricing.json')
    destination = root/'runs'/job['model']/Path(job['task_id']).name
    state = dict(model=job['model'], task_id=job['task_id'], effort=job['effort'], status='completed',
                 source=result['submission'], source_sha256=result['source_sha256'], output=str(output),
                 execution=execution, artifact_sha256=execution['artifact_sha256'],
                 origin_run={'path':str(origin/'run.json'), 'sha256':sha256(origin/'run.json')},
                 origin_generation={'path':str(origin/'generation.json'), 'sha256':sha256(origin/'generation.json')})
    path = destination/'generation_state.json'
    if path.exists() and read(path) != state:
        raise ValueError('Addition retained generation changed')
    write_json(path, state)
    return root, row

def evaluate(job, folder, result):
    root, row = prepare(job, folder, result)
    from tools.experiment_evaluation_recovery import recover_judges, recover_partial_seeds
    source = root/'runs'/job['model']/Path(job['task_id']).name
    recover_partial_seeds(source, folder)
    recover_judges(source/'legacy_baseline', folder, 'addition-baseline', ['components.json'])
    recover_judges(source/'legacy_detail', folder, 'addition-detail', ['detail.json'])
    from tools.execute_effort_addition_variants import run as variants
    from tools.measure_effort_addition_baseline import run as baseline
    from tools.measure_effort_addition_detail import run as detail
    from tools.finalize_effort_addition import finalize
    variants(root, job['task_id'])
    if row['category'] == 'Brief2Scene':
        from tools.measure_effort_addition_numeric import run as numeric
        numeric(root, job['task_id'])
    if row['level'] == 1:
        from tools.measure_effort_addition_integrity import run as integrity
        from tools.measure_effort_addition_delivery import run as delivery
        integrity(root, job['task_id'])
        delivery(root, job['task_id'])
    else:
        from tools.measure_effort_l2_reproducibility import run as reproducibility
        from tools.measure_effort_l2_image_integrity import run as integrity
        from tools.experiment_evaluation_recovery import recover_partial_image_renders, recover_partial_inspections
        recover_partial_inspections(source, folder, job)
        reproducibility(root, job['task_id'])
        recover_partial_image_renders(source, folder)
        integrity(root, job['task_id'])
    from tools.scene_scoring_evidence import prepare_addition
    scoring=prepare_addition(source,level=row['level'])
    if scoring:
        recover_judges(source/'scene_scoring_baseline',folder,'scene-scoring-baseline',['components.json'])
        recover_judges(source/'scene_scoring_detail',folder,'scene-scoring-detail',['detail.json'])
    baseline(root, job['task_id'],output_folder=source/'scene_scoring_baseline' if scoring else None)
    detail(root, job['task_id'],output_folder=source/'scene_scoring_detail' if scoring else None)
    finalize(root, job['task_id'])
    report = root/'main_results'/job['model']/Path(job['task_id']).name/'report.json'
    if read(report).get('S_core') is None:
        raise ValueError('Addition evaluation incomplete')
    return dict(status='completed', report=str(report), report_sha256=sha256(report))
