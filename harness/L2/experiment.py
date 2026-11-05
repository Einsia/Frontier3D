"""Frozen L2 generation/replay batches, explicit interrupted retries and bound summaries."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from harness.common.attempt_log import sha256
from harness.L2.bundle import TASKS, FILES, synchronize
from harness.L2.config import load_policy
from harness.L2.rerun import task_paths
from src.evaluator.l2_requirements import digest
from src.evaluator.spec import L2_EVALUATOR_VERSION
from src.generator.task_adapter import load_benchmark_task

ROOT = Path(__file__).resolve().parents[2]
KINDS = ('generation', 'replay', 'offline-rescore')


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp,path)


@contextmanager
def lock(path):
    with Path(path).open('a') as stream:
        try:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Experiment/trial is already running: '+str(path)) from error
        yield


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            result[path.relative_to(root).as_posix()] = {'symlink': os.readlink(path),
                'sha256': sha256(path) if path.is_file() else None}
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = {'sha256': sha256(path)}
    return result


def readonly(root):
    for p in root.rglob('*'):
        if not p.is_symlink():
            p.chmod(0o555 if p.is_dir() or p.stat().st_mode & 0o111 else 0o444)
    root.chmod(0o555)


def freeze(output, tasks_root, *, kind, tasks=None, trials=1, sources=None, blender=None,
           env_file=None, model=None, copy_runtime=True):
    if kind not in KINDS or type(trials) is not int or trials < 1:
        raise ValueError('Invalid experiment kind/trial count')
    tasks = tasks or ['L2/'+name for name in TASKS]
    if len(set(tasks)) != len(tasks) or any(t not in ['L2/'+n for n in TASKS] for t in tasks):
        raise ValueError('Use unique task IDs for supported L2 tasks')
    if synchronize(tasks_root,check=True):
        raise ValueError('Task harness bundles are stale; run harness.L2.bundle')
    if kind != 'generation' and set(sources or {}) != set(tasks):
        raise ValueError('Replay/offline-rescore need one frozen source mapping per task')
    from src.render.cli import _find_blender
    from harness.L2.headless import RUNTIME, graphics_identity
    local_blender = ROOT/'third_party/blender-5.2.1-linux-x64/blender'
    binary = Path(_find_blender(blender or (local_blender if local_blender.is_file() else None))).resolve()
    graphics = graphics_identity()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output/'snapshot'
    snapshot.mkdir()
    ignore = shutil.ignore_patterns('__pycache__','*.pyc','.pytest_cache')
    shutil.copytree(ROOT/'src',snapshot/'src',ignore=ignore)
    (snapshot/'harness').mkdir()
    if (ROOT/'harness/__init__.py').exists():
        shutil.copy2(ROOT/'harness/__init__.py',snapshot/'harness/__init__.py')
    for name in ('common','L2'):
        shutil.copytree(ROOT/'harness'/name,snapshot/'harness'/name,ignore=ignore)
    versions, configs, requirements, efforts = {}, {}, {}, set()
    source_map = {}
    for task_id in tasks:
        task = load_benchmark_task(task_id,Path(tasks_root))
        task.validate_materialized_assets()
        config_path, _, spec = task_paths(task)
        policy = load_policy(config_path,task_id,spec)
        destination = snapshot/'tasks'/task_id
        (destination/'environment').mkdir(parents=True)
        for name in ('task.toml',task.instruction_path.name):
            shutil.copy2(task.root/name,destination/name)
        if (task.root/'instruction.zh.md').is_file():
            shutil.copy2(task.root/'instruction.zh.md',destination/'instruction.zh.md')
        (destination/'harness').mkdir()
        for name in FILES:
            shutil.copy2(task.root/'harness'/name,destination/'harness'/name)
        for relative in task.environment_files:
            target = destination/'environment'/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(task.environment_dir/relative,target)
        req = policy.requirements
        if req.get('calibration_record'):
            import copy
            from src.evaluator.l2_requirements import apply_calibration
            calibration = copy.deepcopy(req['calibration_record'])
            for check_id, decision in calibration['response']['decisions'].items():
                for index, sample in enumerate(decision.get('samples', [])):
                    asset = snapshot/'calibration'/task_id/(digest(check_id)[:16]+f'-{index}.json')
                    asset.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(sample['evidence_path'],asset)
                    sample['evidence_path'] = str(asset)
            req = apply_calibration(calibration['baseline_requirements'],calibration['response'])
            atomic(destination/'harness/requirements.json',req)
        versions[task_id], configs[task_id], requirements[task_id] = spec.digest, policy.digest, digest(req)
        from harness.common.config import load_config
        efforts.add(load_config(config_path,level=2,task_prefix='L2/').reasoning_effort)
        if kind != 'generation':
            item = sources[task_id]
            source = Path(item['submission']).resolve()
            target = snapshot/'sources'/task_id
            target.mkdir(parents=True)
            if kind == 'replay':
                code = source/'solution.py' if source.is_dir() else source
                if not code.is_file() or code.name != 'solution.py':
                    raise ValueError('Replay requires solution.py')
                shutil.copy2(code,target/'solution.py')
                source_map[task_id] = {'submission': str(target.relative_to(snapshot))}
            else:
                # Offline evidence never creates fresh execution/integrity claims.
                evidence = json.loads(source.read_text())
                shutil.copy2(source,target/'evidence.json')
                source_map[task_id] = {'evidence': str((target/'evidence.json').relative_to(snapshot)),
                                      'original_evidence_sha256': digest(evidence)}
            if item.get('generation_record'):
                generation = Path(item['generation_record'])
                raw = json.loads(generation.read_text())
                if raw.get('task_id') != task_id:
                    raise ValueError('Source generation task mismatch')
                if kind == 'replay' and raw.get('artifact_sha256',{}).get('solution.py') != sha256(target/'solution.py'):
                    raise ValueError('Source code does not match generation record')
                shutil.copy2(generation,target/'generation_record.json')
                source_map[task_id]['generation_record'] = str((target/'generation_record.json').relative_to(snapshot))
    if len(efforts) != 1:
        raise ValueError('Do not mix reasoning efforts in one experiment')
    generator = None
    if kind == 'generation':
        from src.generator.client import GeneratorConfig
        from harness.L2.generation_sandbox import native_codex
        generator = GeneratorConfig.from_env(env_file)
        model = model or generator.model
        codex = native_codex(generator.codex_binary)
    runtime = {'copied': copy_runtime, 'host_kernel': os.uname().release,
        'host_python_binary': str(Path(sys.executable).resolve()),
        'host_python_sha256': sha256(Path(sys.executable).resolve()),
        'packages': {p.metadata['Name']:p.version for p in importlib.metadata.distributions() if p.metadata['Name']},
        'limitation': 'Host kernel, system libraries and Python standard library remain host dependencies; this is not a VM/container image.'}
    if copy_runtime and sys.prefix == sys.base_prefix:
        raise ValueError('Use the project virtualenv to freeze the Python runtime')
    if copy_runtime:
        shutil.copytree(binary.parent,snapshot/'third_party/blender',symlinks=True,ignore=ignore)
        shutil.copytree(RUNTIME,snapshot/'third_party/mesa-headless',symlinks=True,ignore=ignore)
        shutil.copytree(Path(sys.prefix),snapshot/'.venv',symlinks=True,ignore=ignore)
        python_path, blender_path = '.venv/bin/python', 'third_party/blender/blender'
        if generator:
            shutil.copytree(codex.parent.parent,snapshot/'third_party/codex',symlinks=True,ignore=ignore)
            runtime['codex'] = 'third_party/codex/'+codex.relative_to(codex.parent.parent).as_posix()
    else:
        # Intended for local development tests; never advertised as an archived runtime.
        python_path, blender_path = sys.executable, str(binary)
        (snapshot/'third_party').mkdir()
        (snapshot/'third_party/mesa-headless').symlink_to(RUNTIME.resolve(),target_is_directory=True)
        runtime['shared_files'] = {str(binary):sha256(binary),graphics['egl_library']:graphics['egl_library_sha256']}
        if generator:
            runtime['codex'] = str(codex)
            runtime['shared_files'][str(codex)] = sha256(codex)
    runtime.update(python=python_path,blender=blender_path)
    files = inventory(snapshot)
    atomic(output/'snapshot-files.json',files)
    manifest = {'schema_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
        'evaluation_kind':kind,'evaluator_version':L2_EVALUATOR_VERSION,
        'model':model if kind=='generation' else None, 'reasoning_effort':next(iter(efforts)),
        'generator_endpoint_sha256': digest(generator.base_url) if generator else None,
        'spec_sha256':versions,'harness_config_sha256':configs,'requirements_sha256':requirements,
        'source_map':source_map,'runtime':runtime,
        'trials':[{'id':f'{t.split("/")[-1]}-{i:03d}','task_id':t,'trial_id':str(i)} for t in tasks for i in range(trials)],
        'snapshot_index_sha256':sha256(output/'snapshot-files.json')}
    atomic(output/'manifest.json',manifest)
    atomic(output/'seal.json',{'manifest_sha256':sha256(output/'manifest.json')})
    for name in ('manifest.json','seal.json','snapshot-files.json'):
        (output/name).chmod(0o444)
    readonly(snapshot)
    return manifest


def verify(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    if sha256(root/'manifest.json') != json.loads((root/'seal.json').read_text())['manifest_sha256']:
        raise ValueError('Frozen manifest changed')
    if sha256(root/'snapshot-files.json') != manifest['snapshot_index_sha256']:
        raise ValueError('Frozen file index changed')
    if inventory(root/'snapshot') != json.loads((root/'snapshot-files.json').read_text()):
        raise ValueError('Frozen snapshot changed')
    runtime = manifest['runtime']
    if sha256(Path(runtime['host_python_binary'])) != runtime['host_python_sha256']:
        raise ValueError('Host Python runtime changed')
    for path, expected in runtime.get('shared_files',{}).items():
        if sha256(Path(path)) != expected:
            raise ValueError('Shared runtime changed')
    return manifest


def aggregate(root, manifest=None, *, reviews=None):
    root = Path(root)
    manifest = manifest or verify(root)
    reviews = reviews or {}
    if set(reviews)-{t['id'] for t in manifest['trials']}:
        raise ValueError('Review map contains unknown trials')
    reports, entries = [], []
    for trial in manifest['trials']:
        state_path = root/'runs'/trial['id']/'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {'status':'pending'}
        entry = {**trial, **state}
        if state.get('status') == 'complete':
            result_path = root/state['result_path']
            if sha256(result_path) != state['result_sha256']:
                raise ValueError('Completed result changed')
            result = json.loads(result_path.read_text())
            report_path = Path(result['report_path'])
            if sha256(report_path) != result['report_sha256']:
                raise ValueError('Completed report changed')
            report = json.loads(report_path.read_text())
            task = trial['task_id']
            if (report['evaluator_version'] != manifest['evaluator_version']
                or report['spec_sha256'] != manifest['spec_sha256'][task]
                or report['task_id'] != task or report['trial_id'] != trial['trial_id']
                or report.get('evaluation_kind') != manifest['evaluation_kind']):
                raise ValueError('Report version/task/kind does not match frozen experiment')
            if manifest['evaluation_kind'] == 'generation' and report.get('model') != manifest['model']:
                raise ValueError('Generation model mismatch')
            if manifest['evaluation_kind'] != 'offline-rescore':
                record_path = Path(result['harness_record'])
                if sha256(record_path) != result['harness_record_sha256']:
                    raise ValueError('Execution record changed')
                record = json.loads(record_path.read_text())
                from src.evaluator.l2_record import validate_record
                from src.evaluator.spec import EvalSpec
                task_root = root/'snapshot/tasks'/task
                spec = EvalSpec.load(task_root/'harness/eval_spec.json')
                validate_record(record,spec,report['artifact_sha256'],record_path=record_path,
                    trusted_runs_root=record_path.parent.parent,submission=Path(result['submission']),
                    assets_root=task_root,task_id=task,harness_config=task_root/'harness/harness.toml')
                reports.append(report)
            entry['report_path'] = str(report_path)
            if trial['id'] in reviews:
                from harness.L2.review import validate_response
                review = reviews[trial['id']]
                packet = json.loads(Path(review['packet']).read_text())
                response = json.loads(Path(review['response']).read_text())
                if packet['report']['sha256'] != result['report_sha256'] or Path(packet['report']['path']).resolve() != report_path.resolve():
                    raise ValueError('Human review refers to another trial report')
                entry['human_review'] = validate_response(packet,response)
                entry['human_review_inputs'] = {name:{'path':review[name],'sha256':sha256(Path(review[name]))} for name in ('packet','response')}
        entries.append(entry)
    complete = len([e for e in entries if e['status']=='complete'])
    aggregate_report = None
    if reports and complete == len(manifest['trials']):
        from src.evaluator.reporting import summarize_l2
        aggregate_report = summarize_l2(reports)
    summary = {'evaluation_kind':manifest['evaluation_kind'],'evaluator_version':manifest['evaluator_version'],
        'manifest_sha256':sha256(root/'manifest.json'),'planned':len(entries),'complete':complete,
        'trials':entries,'automatic_summary':aggregate_report,
        'formal_score_eligible':bool(reports) and complete==len(entries) and all(
            e.get('human_review',{}).get('formal_score_eligible') is True for e in entries),
        'note':'Pending/interrupted/infrastructure failures remain listed. No partial batch level score; automatic results are not human approval.'}
    atomic(root/'summary.json',summary)
    return summary


def replay_task(task_id, tasks_root, source, output, *, trial_id, blender, generation_record=None):
    from harness.L2.rerun import rerun_submission
    from harness.L2.budget import has_timeout
    task = load_benchmark_task(task_id,tasks_root)
    config, _, spec = task_paths(task)
    policy = load_policy(config,task_id,spec)
    rounds, costs = [], {}
    for limit in policy.timeout_steps:
        result = rerun_submission(task_id,tasks_root,source,output,trial_id=trial_id,blender=blender,
            generation_record=generation_record,timeout=limit,prior_costs=costs)
        costs = result.get('costs',{})
        timed_out = has_timeout(json.loads(Path(result['harness_record']).read_text())) or result.get('evaluation_timed_out',False)
        rounds.append({'timeout_seconds':limit,'timed_out':timed_out,**result})
        if not timed_out:
            break
    result['execution_rounds'] = rounds
    return result


def worker(root, trial, attempt, env_file):
    root, attempt = Path(root).resolve(), Path(attempt).resolve()
    with lock(attempt.parent/'worker.lock'):
        manifest = verify(root)
        snapshot = root/'snapshot'
        def runtime_path(name):
            p = Path(manifest['runtime'][name])
            return p if p.is_absolute() else snapshot/p
        try:
            output = attempt/'outputs'
            task_id, trial_id = trial['task_id'],trial['trial_id']
            kind = manifest['evaluation_kind']
            if kind == 'generation':
                from src.generator.client import GeneratorConfig
                if digest(GeneratorConfig.from_env(env_file).base_url) != manifest['generator_endpoint_sha256']:
                    raise ValueError('Generator endpoint changed after freezing')
                from harness.L2.run import run_task
                result = run_task(task_id,snapshot/'tasks',output,trial_id=trial_id,
                    blender=runtime_path('blender'),env_file=env_file,model=manifest['model'],
                    codex_binary=str(runtime_path('codex')))
            elif kind == 'replay':
                source = manifest['source_map'][task_id]
                generation = json.loads((snapshot/source['generation_record']).read_text()) if source.get('generation_record') else None
                result = replay_task(task_id,snapshot/'tasks',snapshot/source['submission'],output,
                    trial_id=trial_id,blender=runtime_path('blender'),generation_record=generation)
            else:
                from src.evaluator.l2 import score_l2
                from src.evaluator.spec import EvalSpec
                source = manifest['source_map'][task_id]
                evidence = json.loads((snapshot/source['evidence']).read_text())
                evidence['harness'] = {}
                # Old absolute image paths cannot silently become current evidence.
                evidence['artifacts'] = {k:{**v,'path':None} for k,v in evidence.get('artifacts',{}).items()}
                evidence['reference_images'] = {}
                spec = EvalSpec.load(snapshot/'tasks'/task_id/'harness/eval_spec.json')
                report = score_l2(spec,evidence)
                report.update(task_id=task_id,task_type=task_id.split('/')[-1],trial_id=trial_id,
                    evaluation_kind=kind,G=None,S_core=None,case_pass=False,
                    diagnostic_only=True,formal_score_eligible=False,
                    note='Offline measurements only; no current execution/integrity or formal score.')
                atomic(attempt/'offline-report.json',report)
                result = {'report_path':str(attempt/'offline-report.json')}
            if not result.get('report_path'):
                raise RuntimeError('Harness produced no evaluation report')
            result['report_sha256'] = sha256(Path(result['report_path']))
            if result.get('harness_record'):
                result['harness_record_sha256'] = sha256(Path(result['harness_record']))
            atomic(attempt/'result.json',result)
            state = {'status':'complete','result_path':str((attempt/'result.json').relative_to(root)),
                     'result_sha256':sha256(attempt/'result.json')}
        except Exception as error:
            # Keep failed work and its logs; never silently retry paid generation.
            state = {'status':'infrastructure_error','error':str(error),'attempt':str(attempt.relative_to(root))}
        atomic(attempt.parent/'state.json',state)
        return state


def run_batch(root, *, env_file=None, jobs=1, retry_interrupted=False):
    root = Path(root).resolve()
    if type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError('jobs must be 1..8')
    with lock(root/'controller.lock'):
        manifest = verify(root)
        snapshot = root/'snapshot'
        python = Path(manifest['runtime']['python'])
        if not python.is_absolute():
            python = snapshot/python
        queue, running = [], []
        for trial in manifest['trials']:
            directory = root/'runs'/trial['id']
            directory.mkdir(parents=True,exist_ok=True)
            with lock(directory/'worker.lock'):
                state_path = directory/'state.json'
                state = json.loads(state_path.read_text()) if state_path.is_file() else {'status':'pending'}
                if state['status'] == 'complete':
                    continue
                if state['status'] in {'running','interrupted','infrastructure_error'}:
                    state['status'] = 'interrupted' if state['status']=='running' else state['status']
                    atomic(state_path,state)
                    if not retry_interrupted:
                        continue
                queue.append(trial)
        while queue or running:
            while queue and len(running) < jobs:
                trial = queue.pop(0)
                directory = root/'runs'/trial['id']
                attempt = directory/('attempt-'+uuid.uuid4().hex)
                attempt.mkdir()
                atomic(directory/'state.json',{'status':'running','attempt':str(attempt.relative_to(root))})
                command = [str(python),'-B','-m','harness.L2.experiment','worker','--experiment',str(root),
                    '--trial',trial['id'],'--attempt',str(attempt)]
                if env_file:
                    command += ['--env-file',str(Path(env_file).resolve())]
                log = (attempt/'controller.log').open('w')
                environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
                environment.pop('PYTHONPATH',None)
                process = subprocess.Popen(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,env=environment)
                running.append((process,log,directory))
            for item in list(running):
                process,log,directory = item
                if process.poll() is not None:
                    log.close()
                    state = json.loads((directory/'state.json').read_text())
                    if state['status']=='running':
                        atomic(directory/'state.json',{**state,'status':'interrupted','returncode':process.returncode})
                    running.remove(item)
            if running:
                time.sleep(.25)
        return aggregate(root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['freeze','verify','run','summary','worker'])
    parser.add_argument('--experiment',type=Path,required=True)
    parser.add_argument('--tasks-root',type=Path,default=Path('data/3dbench/task'))
    parser.add_argument('--kind',choices=KINDS,default='generation')
    parser.add_argument('--tasks',nargs='+')
    parser.add_argument('--trials',type=int,default=1)
    parser.add_argument('--sources',type=Path)
    parser.add_argument('--reviews',type=Path)
    parser.add_argument('--blender',type=Path)
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--model')
    parser.add_argument('--shared-runtime',action='store_true')
    parser.add_argument('--jobs',type=int,default=1)
    parser.add_argument('--retry-interrupted',action='store_true')
    parser.add_argument('--trial')
    parser.add_argument('--attempt',type=Path)
    args = parser.parse_args(argv)
    if args.operation=='freeze':
        result = freeze(args.experiment,args.tasks_root,kind=args.kind,tasks=args.tasks,trials=args.trials,
            sources=json.loads(args.sources.read_text()) if args.sources else None,blender=args.blender,
            env_file=args.env_file,model=args.model,copy_runtime=not args.shared_runtime)
    elif args.operation=='verify':
        result = verify(args.experiment)
    elif args.operation=='summary':
        result = aggregate(args.experiment,reviews=json.loads(args.reviews.read_text()) if args.reviews else None)
    elif args.operation=='run':
        result = run_batch(args.experiment,env_file=args.env_file,jobs=args.jobs,retry_interrupted=args.retry_interrupted)
    else:
        manifest = json.loads((args.experiment/'manifest.json').read_text())
        trial = next(t for t in manifest['trials'] if t['id']==args.trial)
        result = worker(args.experiment,trial,args.attempt,args.env_file)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if args.operation == 'worker':
        return 0 if result['status'] == 'complete' else 1
    if args.operation == 'run':
        return 0 if result['complete'] == result['planned'] else 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
