"""Fresh L3 campaigns: explicit generation, independent verification, and CSV export."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re

HERE = Path(__file__).resolve().parent
CODE = HERE / 'codebase'

def load(path):
    return json.loads(path.read_text())

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def selected_harness(model, requested=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*',model):
        raise ValueError('Model ID must contain safe, relative identifier segments')
    registry=load(HERE.parents[2]/'configs/release/model-harness-contract.json')
    policy=load(HERE.parents[2]/'configs/release/generator-harnesses.json')
    row=next((r for r in registry['models'] if r['model'].casefold()==model.casefold()),None)
    selected=row['harness_id'] if row else next((h for prefix,h in policy['model_prefixes'].items() if model.casefold().startswith(prefix.casefold())),None)
    if selected:
        native=policy['native_names'][selected]
        if requested is not None and requested!=native:
            raise ValueError(f'{model} generation requires '+('Claude Code' if native=='claude' else native)+' for L1/L2/L3')
        return native
    return requested or policy['native_names'][policy['default']]

def configure(campaign):
    os.environ['L3_EXPERIMENT_BATCH'] = str(campaign)
    sys.path.insert(0, str(CODE))
    from tools import l3_leaderboard_batch as batch
    batch.B = campaign
    return batch

def canonical_task(value):
    if not value:return value
    for row in load(HERE/'task-index.json'):
        identities={row['task_key'],row.get('release_task_id'),Path(row.get('release_task_id','')).name}
        identities.update(row.get('legacy_task_ids',[]))
        if value in identities:
            return row['task_key']
    raise ValueError('Unknown L3 task identity: '+value)

def selected(campaign, task):
    task = canonical_task(task)
    rows = load(campaign / 'manifest.json')['rows']
    rows = [r for r in rows if r.get('enabled', True) and (not task or r['task_key'] == task)]
    if not rows:
        raise ValueError('No matching enabled campaign rows')
    return rows

def validate_release():
    import importlib.util
    spec = importlib.util.spec_from_file_location('l3_release_resource_check', HERE / 'check_resources.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_resources()


def doctor(args):
    from doctor import check
    result = check(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result['errors'] else 0


def initialize(args):
    selected_harness(args.model,args.harness)
    registry=load(HERE.parents[2]/'configs/release/model-harness-contract.json')
    row=next((r for r in registry['models'] if r['model'].casefold()==args.model.casefold()),None)
    expected=row['effort'] if row else 'max'
    if args.effort is None:args.effort=expected
    if args.effort!=expected:raise ValueError('Model contract requires effort '+expected)
    validate_release()
    campaign = args.campaign.resolve()
    if (campaign / 'manifest.json').exists() or (campaign / 'settings.json').exists():
        raise ValueError('Use a fresh campaign directory')
    batch = configure(campaign)
    save(campaign / 'settings.json', {
        'scoring_protocol': 'l3-perceptual-quality-v5',
        'variants': [{'model': args.model, 'effort': args.effort,
                      'harness': selected_harness(args.model,args.harness), 'group': args.group}],
        'tasks': [canonical_task(t) for t in args.task] if args.task else [], 'gpu_ids': [args.gpu],
        'group_workers': {args.group: 1}, 'api_concurrency': {'openai': 1},
        'scoring_workers': 1,
    })
    shutil.copytree(HERE / 'scoring-specs', campaign / 'evaluations/quality-v5-specs')
    batch.initialize()

def generate(args):
    validate_release()
    campaign = args.campaign.resolve()
    batch = configure(campaign)
    if not os.environ.get('L3_UE_IMAGE'):
        raise ValueError('Set L3_UE_IMAGE to the locally built runtime image')
    if not batch.CLI.is_dir():
        raise ValueError('Set L3_NATIVE_CLI to the installed native CLI node_modules directory')
    engine = args.engine.resolve()
    if not (engine / 'Engine/Binaries/Linux/UnrealEditor-Cmd').is_file():
        raise ValueError('Supply a dedicated, complete writable UE engine copy')
    slot = campaign / 'engines/slot-00'
    slot.parent.mkdir(parents=True, exist_ok=True)
    if slot.exists() and slot.resolve() != engine:
        raise ValueError('Campaign slot already points to a different engine')
    if not slot.exists():
        slot.symlink_to(engine, target_is_directory=True)
    settings = load(campaign / 'settings.json')
    settings['gpu_ids'] = [args.gpu]
    save(campaign / 'settings.json', settings)
    for row in selected(campaign, args.task):
        if not (batch.P / (row['group'] + '.json')).is_file():
            raise ValueError('Missing private provider configuration for group ' + row['group'])
        state_path = Path(row['output']) / 'state.json'
        if state_path.exists() and load(state_path).get('status') == 'generated':
            continue
        batch.worker(row, 0)
        if load(state_path).get('status') != 'generated':
            raise RuntimeError('Generation incomplete; inspect preserved state and logs: ' + row['id'])

def evaluate(args):
    validate_release()
    campaign = args.campaign.resolve()
    for row in selected(campaign, args.task):
        out = campaign / 'evaluations/fresh' / row['id']
        command=[
            sys.executable, str(HERE / 'verify.py'), '--task', row['task_key'],
            '--trial', row['output'], '--output', str(out),
            '--engine', str(args.engine.resolve()), '--gpu', str(args.gpu),
            '--model', row['model'], '--effort', row['effort'],
            '--provider', str(args.provider.resolve()), '--reward', str(out / 'reward.txt'),
        ]
        if getattr(args,'resume',False):command+=['--resume']
        subprocess.run(command, check=True)

def validate(args):
    validate_release()
    sys.path.insert(0, str(CODE))
    from harness.L3.Suite.submission_binding import validate_submission
    for row in selected(args.campaign.resolve(), args.task):
        validate_submission(Path(row['output']), row['task_key'], row['model'], row['effort'])

def export(args):
    campaign = args.campaign.resolve()
    rows = []
    for row in selected(campaign, None):
        report = campaign / 'evaluations/fresh' / row['id'] / 'review-v5' / row['task_key'] / row['model'] / 'summary.json'
        result = load(report) if report.is_file() else {}
        valid = result.get('status') == 'measured' and result.get('protocol') == 'l3-perceptual-quality-v5'
        release=next(t for t in load(HERE/'task-index.json') if t['task_key']==row['task_key'])
        rows.append({'task': row['task_key'],'task_id':release['release_task_id'], 'model': row['model'], 'effort': row['effort'],
                     'status': result.get('status', 'pending'),
                     'score_100': result.get('score_100') if valid else None,
                     'report': str(report.relative_to(campaign)) if report.is_file() else ''})
    output = args.output.resolve() if args.output else campaign / 'scores.csv'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(output)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list', help='List the 15 supported L3 tasks')
    listing.set_defaults(func=lambda a: print('\n'.join(r.get('release_task_id',r['task_key']) + '\t' + r['task_key'] + '\t' + r['title'] for r in load(HERE / 'task-index.json'))))
    preflight = sub.add_parser('doctor', help='Offline source and host preflight')
    preflight.add_argument('--resources-only', action='store_true')
    preflight.add_argument('--engine', type=Path)
    preflight.add_argument('--provider', type=Path)
    preflight.add_argument('--verify-assets', action='store_true')
    preflight.set_defaults(func=doctor)
    init = sub.add_parser('init', help='Create a fresh campaign; makes no model calls')
    init.add_argument('--campaign', type=Path, required=True)
    init.add_argument('--model', default='gpt-6.1-sol'); init.add_argument('--effort', choices=['max','xhigh','high'])
    init.add_argument('--harness', choices=['codex','claude','kimi','dsh','zcode','gemini'])
    init.add_argument('--group', default='openai'); init.add_argument('--task', action='append')
    init.add_argument('--gpu', type=int, default=0); init.set_defaults(func=initialize)
    for command, func in [('generate', generate), ('evaluate', evaluate)]:
        cmd = sub.add_parser(command)
        cmd.add_argument('--campaign', type=Path, required=True)
        cmd.add_argument('--task', help='Run one selected task; omit to run the campaign sequentially')
        cmd.add_argument('--engine', type=Path, required=True); cmd.add_argument('--gpu', type=int, default=0)
        if command == 'evaluate':
            cmd.add_argument('--provider', type=Path, required=True)
            cmd.add_argument('--resume',action='store_true')
        cmd.set_defaults(func=func)
    exp = sub.add_parser('export'); exp.add_argument('--campaign', type=Path, required=True)
    exp.add_argument('--output', type=Path); exp.set_defaults(func=export)
    validation = sub.add_parser('validate', help='Validate frozen submissions without UE/model calls')
    validation.add_argument('--campaign', type=Path, required=True)
    validation.add_argument('--task')
    validation.set_defaults(func=validate)
    args = p.parse_args(); return args.func(args)

if __name__ == '__main__':
    raise SystemExit(main())
