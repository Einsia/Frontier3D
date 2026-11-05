"""New L1 case lifecycle; no orchestration is copied into task harnesses."""
from __future__ import annotations
from harness.common.experiment_policy import (GENERATION_TIMEOUT, GENERATION_TOTAL_TIMEOUT, EXECUTION_TIMEOUT, EVALUATION_TIMEOUT)

import importlib.util
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from harness.L1.common.reproduction import compare_seed_artifacts
from src.evaluator.l1_case import load_case
from src.evaluator.spec import EVALUATOR_VERSION

from .feedback import DEFAULT_ATTEMPTS, retry_policy
from .generator import generate
from .runtime import blender_command, retry, run_process, seconds
from .tasks import PROJECT, TASKS, load_task, regular, sha256, write_json

MAX_FILES = 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024
IGNORED = {'evaluation', 'renders', 'logs', '__pycache__', '.git'}


def tree_files(root: Path, *, exclude=(), max_bytes=MAX_SOURCE_BYTES):
    """Reject links/devices before touching candidate contents; retain helpers."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Expected a real submission directory')
    files, size = {}, 0
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if relative.parts[0] in exclude or any(p in IGNORED for p in relative.parts):
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f'Nonregular submission entry: {relative}')
        size += path.stat().st_size
        if len(files) >= MAX_FILES or size > max_bytes:
            raise ValueError('Submission file/byte limit exceeded')
        files[str(relative)] = path
    return files


def snapshot(root, target, *, exclude=(), max_bytes=MAX_SOURCE_BYTES):
    files = tree_files(root, exclude=exclude, max_bytes=max_bytes)
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, path in files.items():
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        before = sha256(path)
        shutil.copyfile(path, dest)
        if sha256(dest) != before or sha256(path) != before:
            raise ValueError(f'Submission changed during snapshot: {name}')
        hashes[name] = before
    return hashes


def unchanged(root, hashes):
    try:
        return all(sha256(regular(root, name)) == digest for name, digest in hashes.items())
    except (ValueError, OSError):
        return False


def implementation_hashes():
    return {'src/run_usage.py': sha256(PROJECT/'src/run_usage.py'), **{str(p.relative_to(PROJECT)): sha256(p)
            for directory in ('orchestrator', 'src/evaluator', 'harness/L1/common', 'src/generator')
            for p in sorted((PROJECT / directory).glob('*.py'))}}


def execute(task, source, source_hashes, directory, *, blender, runtime, image, seed,
            attempts, deadline, attempt_timeout):
    directory.mkdir()

    def attempt(index, end):
        workspace = directory / f'attempt-{index:02d}'
        public = task.stage(workspace)
        for name in source_hashes:
            destination = workspace / 'output' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(regular(source, name), destination)
        command, container = blender_command(workspace, blender, runtime=runtime, image=image, seed=seed,
                                             memory="8g" if task.manifest["level"] == 2 else "4g",
                                             level=task.manifest["level"])
        row = run_process(command, cwd=workspace, directory=directory / f'process-{index:02d}',
                          deadline=end, timeout=attempt_timeout, container=container,
                          env={'THREEDBENCH_SEED': str(seed), 'PYTHONHASHSEED': str(seed)})
        row['workspace'] = str(workspace)
        row['process_directory'] = str(directory / f'process-{index:02d}')
        row['seed'] = seed
        row['inputs_unchanged'] = unchanged(workspace, public)
        row['source_unchanged'] = unchanged(workspace / 'output', source_hashes)
        row['artifact_sha256'] = {}
        try:
            tree_files(workspace / 'output', max_bytes=2*1024**3 if task.manifest['level']==2 else MAX_SOURCE_BYTES)
            for name in task.artifacts:
                path = regular(workspace / 'output', name)
                if path.stat().st_size == 0:
                    raise ValueError(f'Empty artifact: {name}')
                row['artifact_sha256'][name] = sha256(path)
        except (ValueError, OSError) as error:
            row['artifact_error'] = str(error)
            if row['status'] == 'success':
                row['status'] = 'invalid_submission'
        if not row['inputs_unchanged'] or not row['source_unchanged']:
            row['status'] = 'integrity_failed'
        write_json(directory / f'attempt-{index:02d}.json', row)
        return row

    history = retry(attempt, attempts=attempts, deadline=deadline)
    write_json(directory / 'attempts.json', history)
    return history


def generation_validator(task, run, manifest, *, blender, runtime, image, seed, attempt_timeout):
    """One public execution per model call; the first working bundle is frozen.

    The validator never inspects private answers or computes a quality score.
    Its successful execution is reused as baseline, with the original paths.
    """
    def validate(submission, directory, deadline):
        manifest['phase'] = 'generation-execution'
        write_json(run / 'run.json', manifest)
        source = directory / 'validation-source'
        source_hashes = snapshot(submission, source)
        history = execute(task, source, source_hashes, directory / 'validation', blender=blender,
                          runtime=runtime, image=image, seed=seed, attempts=1,
                          deadline=deadline, attempt_timeout=attempt_timeout)
        for row in history:
            row['source_sha256'] = source_hashes
        write_json(directory / 'validation/attempts.json', history)
        manifest['attempts']['baseline'] = history
        manifest['phase'] = 'generation'
        write_json(run / 'baseline/attempts.json', history)
        write_json(run / 'run.json', manifest)
        return history
    return validate


def run_case(task_id, *, submission=None, generate_code=False, tasks_root=TASKS,
             output_root=PROJECT / 'data/task_runs', blender=None, runtime='docker',
             image='3dbench-l1-blender:mvp', timeout=None, attempt_timeout=EXECUTION_TIMEOUT, attempts=DEFAULT_ATTEMPTS,
             reproduction=True, generator_runtime='docker', generator_image=None,
             generation_timeout=GENERATION_TIMEOUT, reproduction_timeout=EXECUTION_TIMEOUT, generation_total_timeout=GENERATION_TOTAL_TIMEOUT, env_file=None):
    timeout = timeout if timeout is not None else EVALUATION_TIMEOUT + (generation_total_timeout if generate_code else 0)
    started = time.monotonic()
    deadline = started + seconds(timeout)
    seconds(attempt_timeout)
    seconds(reproduction_timeout)
    policy = retry_policy(attempts)
    if (submission is None) == (not generate_code):
        raise ValueError('Choose exactly one source: --submission or --generate')
    task = load_task(task_id, tasks_root)
    _, spec = load_case(task.root)
    blender = Path(blender or PROJECT / 'third_party/blender-5.2.1-linux-x64/blender').resolve(strict=True)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=task.root.name+'-', dir=output_root))
    manifest = {'protocol': 'l1-case-run-v1', 'task_id': task_id, 'run_dir': str(run),
                'status': 'running', 'phase': 'prepare', 'runtime': runtime, 'image': image,
                'started_monotonic': started, 'deadline_monotonic': deadline,
                'started_utc': datetime.now(timezone.utc).isoformat(), 'orchestrator_pid': os.getpid(),
                'spec_sha256': spec.digest, 'instruction_sha256': sha256(task.root / 'instruction.md'),
                'model_call': generate_code, 'tokens': None, 'attempts': {}, 'retry_policy': policy,
                'implementation_sha256': implementation_hashes(), 'seeds': list(spec.seeds),
                'scope': 'case-specific integration; incomplete requirements remain in the denominator',
                'isolation_scope': 'Docker mounts and resource limits' if runtime == 'docker' else 'local trusted-source execution only'}
    write_json(run / 'run.json', manifest)
    print(f'Run archive: {run}', flush=True)
    try:
        write_json(run / 'configuration/task.json', task.manifest)
        write_json(run / 'configuration/eval_spec.json', spec.to_dict())
        if (task.root / 'harness/evaluation_design.json').exists():
            from src.evaluator.l1_case_design import load_design
            design = load_design(task.root)
            write_json(run / 'configuration/evaluation_design.json', design)
            manifest['evaluation_design_sha256'] = sha256(task.root / 'harness/evaluation_design.json')
        if generate_code:
            manifest['phase'] = 'generation'
            write_json(run / 'run.json', manifest)
            submission, history = generate(task, run, deadline=min(deadline,time.monotonic()+seconds(generation_total_timeout)), timeout=generation_timeout,
                                           attempts=attempts, env_file=env_file, runtime=generator_runtime,
                                           image=generator_image, validate_submission=generation_validator(
                                               task, run, manifest, blender=blender, runtime=runtime,
                                               image=image, seed=0, attempt_timeout=attempt_timeout))
            manifest['generation_attempts'] = history
            deadline = min(deadline,time.monotonic()+EVALUATION_TIMEOUT)
            timeout = min(timeout,EVALUATION_TIMEOUT)
            manifest['evaluation_deadline_monotonic'] = deadline
        source = run / 'source'
        source_hashes = snapshot(Path(submission).resolve(), source, exclude=('scene.blend', 'scene.glb', 'main.png'))
        regular(source, 'solution.py')
        regular(source, 'README.md')
        manifest['source_sha256'] = source_hashes
        outputs = {}
        for label, seed in [('baseline', 0), *((f'seed-{seed}', seed) for seed in spec.seeds)]:
            manifest['phase'] = label
            write_json(run / 'run.json', manifest)
            if generate_code and label == 'baseline':
                history = manifest['attempts']['baseline']
                if history[-1]['source_sha256'] != source_hashes:
                    raise ValueError('Accepted source differs from validated source')
            else:
                history = execute(task, source, source_hashes, run / label, blender=blender, runtime=runtime,
                                  image=image, seed=seed, attempts=attempts, deadline=deadline,
                                  attempt_timeout=attempt_timeout)
            manifest['attempts'][label] = history
            if history and history[-1]['status'] == 'success':
                outputs[label] = Path(history[-1]['workspace']) / 'output'
            if label == 'baseline' and label not in outputs:
                raise RuntimeError('Baseline execution failed; inspect baseline/attempts.json')
        manifest['phase'] = 'reproduction'
        write_json(run / 'run.json', manifest)
        per_seed, seed_runs = {}, {}
        scoring_reserve = min(180., timeout*.25)
        from src.evaluator.l1_seed_quality import quality_check
        quality_reserve = min(240. * len(spec.seeds), timeout * .45) if quality_check(spec) else 0.
        reproduction_reserve = scoring_reserve + quality_reserve
        for position, seed in enumerate(spec.seeds):
            output = outputs.get(f'seed-{seed}')
            result = {'status': 'not_measurable' if output is None else 'not_configured',
                      'reason': 'Seed execution failed' if output is None else 'Comparison explicitly disabled'}
            if reproduction and output is not None:
                now = time.monotonic()
                share = max(0., deadline-reproduction_reserve-now)/(len(spec.seeds)-position)
                seed_deadline = min(deadline-reproduction_reserve, now+min(reproduction_timeout, share))
                manifest['phase'] = f'reproduction/{seed}'
                write_json(run / 'run.json', manifest)
                try:
                    if seed_deadline <= now:
                        raise TimeoutError('No reproduction budget remains before the scoring reserve')
                    result = compare_seed_artifacts(blender=blender, spec_path=run / 'configuration/eval_spec.json',
                                                    trusted_root=run,
                                                    original_artifacts={name: outputs['baseline'] / name for name in ('scene.blend', 'scene.glb')},
                                                    seed_root=output, output_root=run / f'reproduction/{seed}',
                                                    task_id=task_id, trial_id=run.name, program_seed=seed,
                                                    timeout=reproduction_timeout, deadline=seed_deadline)
                except (OSError, ValueError, RuntimeError) as error:
                    result = {'protocol': 'l1-reproduction-v1', 'status': 'not_measurable',
                              'reason': str(error)[:2048], 'failure_code': getattr(error, 'code', type(error).__name__),
                              'inspections': getattr(error, 'reproduction_inspections', {})}
                result['orchestrator_budget'] = {'deadline_monotonic': seed_deadline,
                                                 'run_deadline_monotonic': deadline,
                                                 'scoring_reserve_seconds': scoring_reserve,
                                                 'seed_quality_reserve_seconds': quality_reserve}
            per_seed[str(seed)] = result
            seed_runs[str(seed)] = {'passed': output is not None, 'reproduction_status': result['status']}
            if output is not None:
                seed_runs[str(seed)]['artifact_sha256'] = manifest['attempts'][f'seed-{seed}'][-1]['artifact_sha256']
            write_json(run / f'reproduction/seed-{seed}.json', result)
        comparison = {'protocol': 'l1-reproduction-v1', 'status': 'ok' if all(r['status'] == 'ok' for r in per_seed.values()) else 'not_measurable' if any(r['status'] in {'not_measurable', 'not_configured'} for r in per_seed.values()) else 'failed',
                      'expected_seeds': list(spec.seeds), 'denominator': len(spec.seeds), 'per_seed': per_seed}
        scored = run / 'submission'
        snapshot(outputs['baseline'], scored)
        record = {'evaluator_version': EVALUATOR_VERSION, 'spec_sha256': spec.digest,
                  'artifact_sha256': {name: sha256(regular(scored, name)) for name in task.artifacts},
                  'execution_passed': True, 'integrity_passed': unchanged(source, source_hashes),
                  'seed_runs': seed_runs, 'reproduction_consistency': comparison}
        if quality_check(spec):
            from .l1_seed_quality import collect_seed_quality
            manifest['phase'] = 'seed_quality'
            write_json(run / 'run.json', manifest)
            record['seed_quality'] = collect_seed_quality(task, spec, outputs, record, blender=blender,
                                                         run=run, deadline=deadline, timeout=timeout,
                                                         scoring_reserve=scoring_reserve)
        write_json(run / 'execution_record.json', record)
        manifest['phase'] = 'scoring'
        write_json(run / 'run.json', manifest)
        entry = importlib.util.spec_from_file_location('l1_case_entry', task.root / 'harness/evaluate.py')
        module = importlib.util.module_from_spec(entry)
        entry.loader.exec_module(module)
        report = module.evaluate(scored, blender, harness_record=record, timeout=timeout, deadline=deadline)
        manifest.update(status='evaluation_failed' if report.get('scoring_failed') or report.get('budget_exhausted') else 'scored',
                        phase='finished', report_path=report['report_path'], evidence_path=report['evidence_path'],
                        case_pass=report['case_pass'], S_core=report['S_core'], S_diagnostic=report['S_diagnostic'])
    except BaseException as error:
        manifest.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'failed',
                        error_type=type(error).__name__, error=str(error)[:2048])
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        manifest['elapsed_seconds'] = time.monotonic()-started
        manifest['implementation_unchanged'] = manifest['implementation_sha256'] == implementation_hashes()
        write_json(run / 'run.json', manifest)
    return manifest
