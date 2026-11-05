"""Evaluate immutable accepted L1 candidates with archived measurement evidence.

Every partial result is archived; a technical measurement failure remains null.
Resuming never resamples an accepted judgment. Generation is independently
scheduled, so queued/running candidates are not mistaken for missing answers.
"""

from __future__ import annotations
import os

import argparse

import fcntl

from concurrent.futures import ThreadPoolExecutor, as_completed

from dataclasses import replace

import json

import os

import signal

from pathlib import Path

import subprocess

import sys

import time

import numpy as np

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from orchestrator.tasks import sha256, write_json

from harness.L1.l2_aligned_judge import judge_aligned

from harness.L2.vlm_judge import JudgeConfig

from src.evaluator.l1_l2_alignment import aggregate, measure_data, measure_image, SYSTEM_GATES, BRIEF

from src.evaluator.l1_assembly_support import measure as measure_support

from src.evaluator.l1_edit_validity import combine, gate, system_gate

from src.evaluator.spec import EvalSpec

from benchmark.compat import classify, now

MODELS = ('gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra')

BLENDER = blender_path()

def read(path):
    return json.loads(Path(path).read_text())

def bind(path, bindings, expected=None):
    path = Path(path).resolve(strict=True)
    data_root = Path(os.environ.get('THREEDBENCH_RUN_ROOT', ROOT/'data'))
    relative = path.relative_to(data_root) if path.is_relative_to(data_root) else None
    packaged_run = (relative is not None and len(relative.parts) >= 4
                    and relative.parts[0].startswith('3dbench_merge_')
                    and relative.parts[1] == 'agent-run')
    # Packaged campaigns reference their task inputs by symlink. Resolving that
    # link leaves agent-run; require a frozen plan digest for these inputs.
    packaged_input = (expected is not None and relative is not None
                      and len(relative.parts) >= 5
                      and relative.parts[0].startswith('3dbench_merge_')
                      and relative.parts[1] == 'tasks')
    public_run = bool(os.environ.get('THREEDBENCH_RUN_ROOT')) and path.is_relative_to(data_root)
    public_input = expected is not None and path.is_relative_to(ROOT/'data/3dbench/tasks')
    if not public_run and not public_input and not path.is_relative_to(data_root/'task_runs') and not packaged_run and not packaged_input:
        raise ValueError('Evidence outside experiment archive: '+str(path))
    value = sha256(path)
    if expected and value != expected:
        raise ValueError('Evidence digest changed: '+str(path))
    bindings[str(path)] = value
    return path

def flatten(report):
    return {c['id']: c for group in report.get('modules', {}).values() for c in group.get('checks', [])}

def system_gates(run_root, run, report, record, bindings):
    gates = {k: report.get('gates', {}).get(k, gate('not_measurable')) for k in SYSTEM_GATES[:4]}
    if record.get('execution_passed') is True:
        gates['execution'] = gate('passed')
    if record.get('integrity_passed') is True:
        gates['integrity'] = gate('passed')
    baseline_system = [system_gate(c)['measurement_status'] for c in flatten(report).values()
                       if c.get('metric') in {'procedural_materials', 'procedural_material_sequence', 'main_render_consistency'}]
    if baseline_system:
        gates['integrity'] = gate(combine([gates['integrity']['measurement_status'], *baseline_system]))
    states, seed_systems = [], []
    for seed in run['seeds']:
        attempts = run.get('attempts', {}).get(f'seed-{seed}', [])
        last = attempts[-1] if attempts else {}
        state = 'passed' if last.get('status') == 'success' else 'failed' if last.get('status') in {'process_error','timeout','artifact_error','invalid_artifacts'} and last.get('return_code') not in (125,126,127) else 'not_measurable'
        states.append(state)
        evidence = record.get('seed_quality', {}).get('per_seed', {}).get(str(seed), {})
        if evidence.get('report_path') and Path(evidence['report_path']).is_file():
            bind(evidence['report_path'], bindings, evidence.get('report_sha256'))
            seed_report = read(evidence['report_path'])
            if seed_report.get('artifact_sha256') != last.get('artifact_sha256'):
                raise ValueError('Seed report differs from trusted executed artifacts')
            checks = flatten(seed_report)
            for name, value in last.get('artifact_sha256', {}).items():
                bind(Path(last['workspace'])/'output'/name, bindings, value)
            selected = [system_gate(c)['measurement_status'] for c in checks.values()
                        if c.get('metric') in {'procedural_materials','procedural_material_sequence','main_render_consistency'}
                        or c['id'] in {'export','real_geometry','main_loadable','main_dimensions','main_format','readme'}]
            seed_systems.append(combine(selected))
        else:
            seed_systems.append('not_measurable')
    gates['all_seeds'] = gate(combine(states))
    gates['all_seed_quality'] = gate(combine(seed_systems), scope='System/delivery only; semantic failures do not gate quality')
    return gates

def compact_render(command, output, environment, *, timeout=600):
    """Bound native crash recovery to two fresh processes and one deadline."""
    started = time.monotonic()
    attempts = []
    def retain_partial():
        path = output/'native.json'
        if path.exists():
            archive = output/('incomplete-render-'+str(time.time_ns()))
            archive.mkdir(mode=0o777); archive.chmod(0o777)
            path.rename(archive/'native.json')
    for number in range(2):
        log = output/'worker.log'
        if log.exists():
            archive = output/('render-crash-'+str(time.time_ns()))
            archive.mkdir(mode=0o777); archive.chmod(0o777)
            for name in ('worker.log', 'native.json', 'render-attempts.json'):
                path = output/name
                if path.exists(): path.rename(archive/name)
        remaining = timeout-(time.monotonic()-started)
        if remaining <= 0: raise subprocess.TimeoutExpired(command, timeout)
        try:
            with log.open('w') as stream:
                completed = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                    timeout=remaining, env=environment)
        except subprocess.TimeoutExpired:
            attempts.append({'returncode': None, 'status': 'timeout'})
            write_json(output/'render-attempts.json', {'attempts': attempts, 'status': 'timeout'})
            retain_partial()
            raise
        attempts.append({'returncode': completed.returncode})
        write_json(output/'render-attempts.json', {'attempts': attempts,
            'status': 'completed' if completed.returncode == 0 else 'failed'})
        if completed.returncode == 0 and (output/'native.json').is_file(): return
        if completed.returncode not in {-signal.SIGSEGV, -signal.SIGABRT} or number:
            retain_partial()
            raise RuntimeError('Compact native rendering failed; inspect '+str(log))

def collect_native(scene, output, frame, *, studio, main_required, geometry_only=False):
    request = {'scene': str(scene), 'scene_sha256': sha256(scene), 'output': str(output),
               'frame': frame, 'studio': studio, 'main_required': main_required}
    if geometry_only:
        request['geometry_only']=True
    if (output/'native.json').is_file():
        native = read(output/'native.json')
        if native['scene_sha256'] != request['scene_sha256'] or read(output/'request.json') != request:
            raise ValueError('Native cache differs from frozen request')
        for item in [*native['objects'], *native['renders'].values()]:
            if sha256(Path(item['path'])) != item['sha256']:
                raise ValueError('Native cache bytes changed')
        return native
    output.mkdir(parents=True, exist_ok=True)
    write_json(output/'request.json', request)
    command = [str(BLENDER), '--background', '--factory-startup', '--disable-autoexec', '--threads', '2',
               '--python-exit-code', '1', '--python', str(ROOT/'src/evaluator/l1_review_blender.py'), '--']
    environment = {**os.environ, 'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'}
    # Rendering runs in a fresh Blender process. Some evaluated-mesh extraction
    # paths leave process-global Cycles state invalid even after reopening a
    # scene; both phases retain exactly the same immutable candidate bytes.
    geometry_request = output/'geometry-request.json'
    write_json(geometry_request, {**request, 'geometry_only':True})
    with (output/'geometry-worker.log').open('w') as stream:
        completed = subprocess.run([*command, str(geometry_request)], stdout=stream,
            stderr=subprocess.STDOUT, timeout=600, env=environment)
    if completed.returncode or not (output/'native.json').is_file():
        raise RuntimeError('Compact native geometry collection failed; inspect '+str(output/'geometry-worker.log'))
    if geometry_only:
        return read(output/'native.json')
    receipt = output/'geometry.json'
    (output/'native.json').replace(receipt)
    render_request = output/'render-request.json'
    write_json(render_request, {**request, 'render_only':True, 'geometry_receipt_sha256':sha256(receipt)})
    from tools.native_render_budget import budget
    render_seconds, render_threads = budget(request['scene_sha256'], 600, 2)
    render_command = [*command, str(render_request)]
    render_command[render_command.index('--threads')+1] = str(render_threads)
    render_environment = {**environment, 'OMP_NUM_THREADS': str(render_threads)}
    write_json(output/'render-budget.json', {
        'scene_sha256': request['scene_sha256'], 'seconds': render_seconds,
        'threads': render_threads, 'scope': 'process budget only; native recipe unchanged'})
    compact_render(render_command, output, render_environment, timeout=render_seconds)
    return read(output/'native.json')

def review_one(campaign, output, model, row, config):
    dest=output/model/'cases'/Path(row['task_id']).name
    dest.mkdir(parents=True,exist_ok=True)
    with (dest/'.review.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'model':model,'task_id':row['task_id'],'status':'running','S_core':None,
                    'error':'Another review worker owns this case; no duplicated judge call'}
        return _review_one(campaign,output,model,row,config)

def _review_one(campaign, output, model, row, config):
    identity = row['task_id']
    dest = output/model/'cases'/Path(identity).name
    dest.mkdir(parents=True, exist_ok=True)
    if (dest/'report.json').is_file():
        saved = read(dest/'report.json')
        for path, expected in saved['source_bindings'].items():
            bind(path, {}, expected)
        return saved
    bindings = {}
    run_root = Path(row['run_dir']).resolve() if row.get('run_dir') else None
    base = {'task_id': identity, 'model': model, 'evaluation_kind': 'retrospective_l1_strict_review',
            'spec_sha256': row['spec_sha256'], 'instruction_sha256': row['instruction_sha256'],
            'source_run_dir': str(run_root) if run_root else None,
            'candidate_selection': row.get('selection_reason'), 'new_candidate_generations': 0,
            'new_candidate_executions': 0, 'formal_score_eligible': False,
            'annotation_review_status': 'ai_draft_pending_human_calibration',
            'created_utc': now(), 'source_bindings': bindings}
    write_json(dest/'status.json', {**base, 'status':'running'})
    try:
        if not run_root:
            raise ValueError('No terminal run archive')
        bind(run_root/'run.json', bindings, row.get('retained_run_sha256') or row.get('run_sha256'))
        run = read(run_root/'run.json')
        if run['task_id'] != identity or run['spec_sha256'] != row['spec_sha256'] or run['instruction_sha256'] != row['instruction_sha256']:
            raise ValueError('Current task binding mismatch')
        old = read(bind(run['report_path'], bindings)) if run.get('report_path') else {}
        generation = read(run_root/'generation.json') if (run_root/'generation.json').is_file() else {}
        origin = run_root
        if run.get('model_call') is not True and not run.get('provided_source'):
            provenance = row.get('previous_row', {}).get('source_provenance', {})
            origin = Path(provenance['source_run_dir'])
            original = read(bind(origin/'run.json', bindings, provenance['source_run_sha256']))
            if original.get('model_call') is not True or original.get('source_sha256') != run.get('source_sha256'):
                raise ValueError('Retained candidate does not prove original model code')
            generation = read(bind(origin/'generation.json', bindings))
        if (not generation.get('attempts') and not run.get('provided_source')) or any(a.get('model') != model for a in generation.get('attempts', [])):
            raise ValueError('Missing verified model-generation provenance')
        base['model_origin_run'] = str(origin/'run.json')
        base['model_generation_path'] = str(origin/'generation.json')
        if generation:
            bind(origin/'generation.json', bindings)
            if any(a.get('model') != model for a in generation.get('attempts', [])):
                raise ValueError('Generator model identity mismatch')
        if not (run_root/'submission/scene.blend').is_file():
            outcome = classify(run, generation, old)
            failure = outcome == 'model_failure'
            result = {**base, 'status': 'system_invalid' if failure else 'not_measurable',
                      'S_core': 0. if failure else None, 'score_valid': False,
                      'method_version': row['method_version'] if row['category']=='CodeEdit' else
                          'l1-brief-l2aligned-v1.0.0' if row['category']=='Text2Code' else 'l1-reference-l2aligned-v1.0.0',
                      'score_components': {}, 'failure_kind': outcome, 'error': run.get('error'),
                      'missing_components': ['No accepted native artifact'], 'new_judge_calls': 0}
        else:
            record = read(bind(run_root/'execution_record.json', bindings))
            if record.get('spec_sha256') != row['spec_sha256']:
                raise ValueError('Execution record belongs to another spec')
            for name, expected in record['artifact_sha256'].items():
                bind(run_root/'submission'/name, bindings, expected)
            scene = run_root/'submission/scene.blend'
            if row['category'] == 'CodeEdit':
                previous = row.get('previous_row', {})
                rescore = previous.get('rescore')
                if rescore:
                    old = read(bind(rescore['report_path'], bindings, rescore['report_sha256']))
                # CodeEdit's independent geometry/target/preservation method is
                # unchanged; preserve measured components and explain reuse.
                result = {**old, **base, 'codeedit_measurement_reuse': True,
                          'review_note': 'Current task hashes and executed artifacts reverified; existing 40/40/20 per-case measurements reused unchanged.',
                          'old_S_core': old.get('S_core'), 'new_judge_calls': 0}
            else:
                folder = output/'plans'/identity
                plan = read(bind(folder/'alignment.json', bindings))
                bind(folder/'vlm_spec.json', bindings)
                task_root = Path(read(campaign/'campaign.json')['frozen'])/'data/3dbench/tasks'/identity
                for name, expected in plan['sources'].items():
                    bind(task_root/name, bindings, expected)
                main = None
                if row['category'] != 'Text2Code' and run.get('evidence_path'):
                    evidence_path = Path(run['evidence_path'])
                    # JSON remains metadata-only here. Oversized legacy evidence
                    # is not loaded; the independent compact collector recovers it.
                    if evidence_path.stat().st_size < 128*1024*1024:
                        evidence = read(bind(evidence_path, bindings))
                        primary = evidence.get('views', {}).get('primary', {})
                        if primary.get('image'):
                            expected = next(iter(old.get('main_image_comparison', {}).get('per_view', {}).values()), {}).get('hashes', {})
                            if expected.get('scene') == sha256(scene):
                                main = bind(primary['image'], bindings, expected.get('render'))
                native = collect_native(scene, dest/'native', plan['physics']['frame'],
                                        studio=plan['profile']==BRIEF, main_required=main is None)
                bind(dest/'native/native.json', bindings)
                if main is None:
                    main = bind(native['renders']['main']['path'], bindings, native['renders']['main']['sha256'])
                alternate = bind(native['renders']['alternate']['path'], bindings, native['renders']['alternate']['sha256'])
                for obj in native['objects']:
                    bind(obj['path'], bindings, obj['sha256'])
                artifacts = {name: {'path': str(path), 'sha256': sha256(path)} for name,path in
                             [('main.png',main),('alternate.png',alternate),('scene.blend',scene)]}
                measurements = {'physics': measure_support(plan,native)}
                if measurements['physics'].get('status')=='not_measurable':
                    from tools.recover_undefined_candidate import enabled
                    if enabled():
                        from src.evaluator.candidate_robustness import VERSION as ROBUSTNESS
                        measurements['physics'].update(status='measured',score=0.,
                            robustness={'policy':ROBUSTNESS,'classification':'undefined_candidate_contact_geometry'})
                if plan['profile'] == BRIEF:
                    measurements['data'] = measure_data(plan, flatten(old))
                else:
                    annotation = read(bind(folder/'reference_regions.json', bindings))
                    reference = task_root/plan['reference_primary']
                    def pixels(path):
                        return np.asarray(Image.open(path).convert('RGB'),dtype=float)/255
                    measurements['main_image'] = measure_image(plan,pixels(reference),pixels(main),annotation,
                                                               image_sha256=artifacts['main.png']['sha256'])
                write_json(dest/'measurements.json', measurements)
                judgment = judge_aligned(task_root,plan,folder/'vlm_spec.json',{'artifacts':artifacts},
                                         dest/'judge',config=config,tested_model=model,blender=BLENDER)
                gates = system_gates(run_root,run,old,record,bindings)
                result = {**aggregate(plan,gates,measurements,judgment,
                                     artifact_sha256={k:v['sha256'] for k,v in artifacts.items()}),
                          **base, 'old_S_core': old.get('S_core'), 'old_method_version': old.get('method_version'),
                          'review_images': artifacts, 'new_judge_calls': len(judgment.get('attempts',[])),
                          'presentation': 'fixed neutral studio; no authored camera required' if plan['profile']==BRIEF else 'original audited main plus reverse diagnostic view'}
                for file in ('run.json','issues.json','score.json','packet/manifest.json'):
                    if (dest/'judge'/file).is_file():
                        bind(dest/'judge'/file,bindings)
        result['source_bindings'] = bindings
        result['finished_utc'] = now()
        write_json(dest/'report.json', result)
        write_json(dest/'status.json', {'status':result['status'],'S_core':result.get('S_core'),'finished_utc':now()})
        return result
    except Exception as error:
        # A failed measurement never creates a fake zero or cached final report.
        result = {**base,'status':'not_measurable','S_core':None,'error':f'{type(error).__name__}: {error}',
                  'finished_utc':now()}
        write_json(dest/'failure.json', result)
        write_json(dest/'status.json', result)
        return result
