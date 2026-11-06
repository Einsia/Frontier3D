"""Measure the complete frozen detail population for a new-task v2 extension."""
import os

import argparse

from concurrent.futures import ThreadPoolExecutor, as_completed

import fcntl

from pathlib import Path

import sys

from threading import Lock

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig, judge_task

from src.agent_judge.protocol import read_json as read

from src.agent_judge.runtime import run_codex

from src.agent_judge.invocation_policy import compact_judge, sampled_variants

from src.evaluator.legacy_detail import detail_from_criteria

from tools.evaluate_linear_candidate import atomic, pin, exported_scene, addition_exported_scene

from tools.run_l1_strict_review import collect_native, BLENDER

from tools.run_new_tasks import jobdir, verify_task, record_call

from tools.watch_effort_historical import affected

def aggregate(spec, scores, population):
    definitions = {'measurements': [
        {'id': check['id'], 'weight': check['global_weight'],
         'method': 'visual_coverage_deviation'} for check in spec['checks']]}
    return detail_from_criteria(definitions, [c['id'] for c in spec['checks']], scores, population)

def l2_artifacts(current, fmt):
    if fmt != 'native':
        raise ValueError('L2 detail requires native variants')
    names = ('scene.blend', 'main.png', 'alternate.png')
    if not all(name in current for name in names):
        raise ValueError('L2 submitted scene and both authored views required')
    return {name: pin(current[name]['path'], current[name]['sha256']) for name in names}

def native_dependency_assets(scene, receipt):
    """Use only passed dependencies of this exact hash-bound native scene."""
    if receipt.get('scene') != scene or receipt.get('source_unchanged') is not True:
        raise ValueError('Dependency receipt belongs to a different native scene')
    root = Path(scene['path']).resolve().parent
    assets = {}
    for row in receipt['unpacked_dependencies']:
        if row.get('measurement_status') != 'passed':
            continue
        path = Path(row['resolved_path'])
        relative = path.resolve().relative_to(root)
        if not relative.parts or relative.parts[0] != 'assets':
            raise ValueError('Dependency is outside portable output/assets')
        assets[relative.as_posix()] = pin(path, row['sha256'])
    return assets

def run(root, task_id, *, profile=None, output_folder=None):
    campaign = read(root / 'campaign.json')
    row = next(r for r in campaign['records'] if r['task_id'] == task_id)
    verify_task(root, row)
    source = jobdir(root, tested_model(root), task_id)
    generation = read(source / 'generation_state.json')
    if generation['status'] != 'completed' or affected(source):
        raise ValueError('Clean accepted generation required')
    config_root = resource('addition_config') / Path(task_id).name
    plan = read(config_root / 'plan.json')
    spec = read(config_root / 'detail_spec.json')
    for pointer in [plan['rules'], plan['acceptance'], plan['instruction'], *plan['references']]:
        pin(pointer['path'], pointer['sha256'])
    manifest_path = source / 'legacy_execution/variants.json'
    manifest = read(manifest_path)
    if manifest['generation'] != pin(source / 'generation_state.json') or manifest['status'] != 'completed':
        raise ValueError('Complete bound seed executions required')
    population = plan['detail_variants']
    if profile not in {None, 'fast'}:
        raise ValueError('Unsupported detail profile')
    measured_population = (population if profile is None else
                           sampled_variants(population, category=row.get('category')))
    bindings = {'generation': manifest['generation'], 'variants': pin(manifest_path),
                'plan': pin(config_root / 'plan.json'), 'spec': pin(config_root / 'detail_spec.json')}
    scoring_path=source/'scene_scoring_evidence/images.json'
    scoring=read(scoring_path) if scoring_path.exists() else None
    if scoring:
        if scoring['source_variants']!=pin(manifest_path):raise ValueError('Scoring rerender population changed')
        bindings['scoring_evidence']=pin(scoring_path)
    for artifacts in manifest['variants'].values():
        for pointer in artifacts.values():
            pin(pointer['path'], pointer['sha256'])
    folder = Path(output_folder or source / ('legacy_detail' if profile is None else 'legacy_detail_screening'))
    output_name = 'detail.json' if profile is None else 'screening.json'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'case.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (folder / output_name).exists():
            saved = read(folder / output_name)
            if saved['source_bindings'] != bindings:
                raise ValueError('Cached detail evidence changed')
            if profile is None:
                from src.evaluator.legacy_detail import require_full_population
                require_full_population(saved, population)
            if profile is not None and saved.get('measured_variants') != measured_population:
                raise ValueError('Cached screening subset changed')
            for pointer in saved['judge_runs'].values():
                pin(pointer['path'], pointer['sha256'])
            return saved
        config = JudgeConfig(model=judge_model(), effort='medium', timeout=600, attempts=3,
            api_key=judge_key(),
            base_url=campaign['provider_url'], codex=campaign['codex'])
        config = compact_judge(config)

        def invoke(packet, directory, **kwargs):
            execution = run_codex(packet, directory, **kwargs)
            record_call(root, role='judge', model=config.model, tested_model=tested_model(root),
                        task_id=task_id, directory=directory, execution=execution)
            return execution

        references = {str(i): r for i, r in enumerate(plan['references'])}
        scores, provenance = {}, {}
        seed_locks = {v.split('/')[0]: Lock() for v in measured_population}

        def judge_variant(variant):
            seed, fmt = variant.split('/')
            current = manifest['variants'][seed]
            dest = folder / 'variants' / variant
            if row['level'] == 2:
                artifacts = l2_artifacts(current, fmt)
            else:
                with seed_locks[seed]:
                    native = collect_native(Path(current['scene.blend']['path']), folder / 'native' / seed,
                                            1, studio=False, main_required=True)
                    if fmt == 'glb':
                        scene = addition_exported_scene(current, native, folder, seed)
                    else:
                        scene = current['scene.blend']
                    rendered = collect_native(Path(scene['path']), dest / 'render', 1,
                                              studio=False, main_required=True) if fmt == 'glb' else native
                artifacts = {'scene.blend': scene, **{
                k + '.png': {f: v[f] for f in ('path', 'sha256')} for k, v in rendered['renders'].items()}}
            if scoring and fmt=='native':
                from tools.scene_scoring_evidence import checked
                artifacts={k:checked(v) for k,v in scoring['variants'][seed].items()}
            native_assets = {}
            if row['level'] == 1 and fmt == 'native':
                from tools.measure_effort_addition_delivery import dependencies
                dependency_gate = dependencies(scene, source/'legacy_delivery'/seed/'dependencies')
                receipt = dependency_gate['evidence']
                pin(receipt['path'], receipt['sha256'])
                native_assets = native_dependency_assets(scene, read(Path(receipt['path'])))
            result = judge_task(Path(row['task_root']), {'artifacts': artifacts, 'reference_images': references,
                                'native_assets': native_assets},
                {'_vlm_judge': {'version': 'continuous-task-judge-v1', 'spec': spec,
                 'spec_sha256': bindings['spec']['sha256'], 'mode': 'interactive'}},
                dest / 'judge', config=config, tested_model=tested_model(root), blender=BLENDER, invoke=invoke)
            return (variant, result.get('criterion_scores', {}) if result.get('status') == 'scored' else {},
                    pin(dest / 'judge/run.json'))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(judge_variant, v) for v in measured_population]
            for future in as_completed(futures):
                variant, values, pointer = future.result()
                scores[variant], provenance[variant] = values, pointer
                atomic(folder / 'status.json', {'status': 'running', 'task_id': task_id,
                    'finished_variants': list(scores), 'required_variants': population,
                    'measured_variants': measured_population})
        result = {**aggregate(spec, scores, measured_population), 'task_id': task_id,
                  'source_bindings': bindings, 'judge_runs': provenance,
                  'judge_model': config.model, 'judge_effort': config.effort,
                  'required_variants': population, 'measured_variants': measured_population}
        if profile is not None:
            result.update(measurement_status=result['status'], status='screening',
                          screening_score=result.pop('score'), required_variants=population,
                          measured_variants=measured_population, profile=profile)
        atomic(folder / output_name, result)
        atomic(folder / 'status.json', {'status': result['status'], 'task_id': task_id})
        return result
