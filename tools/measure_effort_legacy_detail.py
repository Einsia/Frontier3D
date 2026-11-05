"""Measure frozen legacy visual detail on every required seed/export variant.

Uses the published v1 detail contract underlying v2. It does not replace the
separate legacy baseline or the four task-specific v2 corrections.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from dataclasses import replace

import fcntl

import json

from pathlib import Path

import sys

import os

import subprocess

from threading import Lock

from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig,judge_task

from src.agent_judge.responses_runtime import JUDGE_INSTRUCTIONS

from src.agent_judge.invocation_policy import compact_judge, sampled_variants, detail_single_round_judge

from src.agent_judge.detail_spec import project_detail_spec

from src.agent_judge.protocol import read_json as read,digest

from src.evaluator.legacy_detail import detail_from_mixed_criteria as detail_from_criteria

from tools.evaluate_linear_candidate import artifact_variants,exported_scene,atomic,pin

from tools.run_l1_strict_review import collect_native,BLENDER

from tools.scene_render import render

def contract(task_id, root=None):
    policy=read(resource('legacy_policy'))
    recipe=next(r for r in policy['cases'] if r['task_id']==task_id)
    if root is not None and (Path(root)/'task_revisions.json').is_file():
        revision=read(Path(root)/'task_revisions.json').get('tasks',{}).get(task_id)
        if revision:
            pointer=revision['recipe'];pin(pointer['path'],pointer['sha256'])
            recipe=read(Path(pointer['path']))
            if recipe['task_id']!=task_id:raise ValueError('Replacement detail recipe identity differs')
    if recipe['method']=='keep_legacy':raise ValueError('CodeEdit needs no detail replacement')
    source=Path(recipe['source_plan']['path']);pin(source,recipe['source_plan']['sha256'])
    plan=read(source);spec=read(source.with_name('judge_spec.json'))
    if any(c['method']!='visual_coverage_deviation' and not (
            c['id']=='hinge_kinematics' and c['method']=='normalized_error_kernel') for c in recipe['criteria']):
        raise ValueError('This task requires its native detail collector before aggregation')
    population=read(resource('detail_populations'))[task_id]
    return recipe,plan,spec,population

def screening_profile(population, profile, *, l1, category=None):
    """Return an explicit, screening-only variant subset.

    The fast profile keeps primary and the first published seed, including
    native/export pairs. SingleView keeps its full population after replay
    exposed a large sampling error. Output remains a screening measurement.
    """
    if profile != 'fast':
        raise ValueError('Unknown screening profile: ' + profile)
    return sampled_variants(population, category=category)

def validate_published_references(spec, linear):
    """Validate public images and the before/target images added by the packet builder."""
    references = dict(linear['reference_images'])
    for role in ('before', 'target'):
        pointer = linear.get('edit_context', {}).get(role)
        if pointer is None:
            continue
        name = f'reference/{role}.png'
        if name in references and references[name] != pointer:
            raise ValueError('Conflicting published reference: ' + name)
        references[name] = pointer
    for name, expected in spec['reference_bindings'].items():
        if name not in references:
            raise ValueError('Missing published reference: ' + name)
        pointer = references[name]
        if pointer['sha256'] != expected:
            raise ValueError('Published reference digest changed: ' + name)
        pin(pointer['path'], expected)

def measure(root,task_id,*,export_worker=None,selected_variants=None,allow_tracked_camera=False,output_folder=None,baseline_report=None):
    selected_variants = None if selected_variants is None else list(selected_variants)
    stage = 'legacy_detail' if selected_variants is None else 'legacy_detail_screening'
    folder=Path(output_folder or root/stage/tested_model(root)/Path(task_id).name)
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _measure(root,task_id,folder,export_worker=export_worker,
                        selected_variants=selected_variants,allow_tracked_camera=allow_tracked_camera,baseline_report=baseline_report)

def _measure(root,task_id,folder,*,export_worker=None,selected_variants=None,allow_tracked_camera=False,baseline_report=None):
    row=next(r for r in read(root/tested_model(root)/'batch.json')['cases'] if r['task_id']==task_id)
    if row['status'] in {'queued','running'}:raise ValueError('Generation is still active')
    run_dir=Path(row['run_dir']);run=read(run_dir/'run.json')
    recipe,plan,spec,population=contract(task_id,root)
    native_atoms = [c for c in recipe['criteria'] if c['method']!='visual_coverage_deviation']
    visual_ids = [c['id'] for c in recipe['criteria'] if c['method']=='visual_coverage_deviation']
    detail_frame = next((pair['frame'] for pair in plan.get('view_pairs', [])
                         if pair['candidate']=='candidate/main.png'),1) if native_atoms else 1
    if selected_variants is None:
        measured_population = population
        # LEGACY_DETAIL_VARIANT_LIMIT caps how many variants are judged, keeping the
        # output in legacy_detail/detail.json so finalize() finds it unchanged.
        # Variants are ordered: primary/native, primary/glb, seed-N/native, seed-N/glb …
        # A limit of 2 keeps only the primary seed's native and glb renders.
        limit = int(os.environ.get('LEGACY_DETAIL_VARIANT_LIMIT', '0')) or len(population)
        if limit < len(population):
            measured_population = population[:limit]
    else:
        if not selected_variants or len(selected_variants) != len(set(selected_variants)):
            raise ValueError('Screening variant subset must be nonempty and distinct')
        if set(selected_variants) - set(population):
            raise ValueError('Screening variant is not in the published population')
        measured_population = [v for v in population if v in set(selected_variants)]
    binding={'run':pin(run_dir/'run.json'),'plan':recipe['source_plan'],
        'spec':pin(Path(recipe['source_plan']['path']).with_name('judge_spec.json')),
        'variants':population}
    scoring_images=None
    baseline_path=Path(baseline_report or root/'legacy_baseline'/tested_model(root)/Path('cases')/Path(task_id).name/'report.json')
    if baseline_path.exists():
        scoring_pointer=read(baseline_path).get('scoring_images')
        if scoring_pointer:
            pin(scoring_pointer['path'],scoring_pointer['sha256']);scoring_images=read(Path(scoring_pointer['path']))
            if scoring_images['source_execution_record']!=pin(run_dir/'execution_record.json'):
                raise ValueError('Detail rerenders belong to another native execution')
            binding['scoring_evidence']=scoring_pointer
    campaign=read(root/'campaign.json')
    profile=campaign.get('detail_measurement_profile','full-v1')
    invocation=campaign.get('detail_invocation_profile','compact-v1')
    if invocation not in {'compact-v1','detail-single-round-v1','detail-single-round-cached-v1'}:
        raise ValueError('Unknown detail invocation profile: '+str(invocation))
    if invocation in {'detail-single-round-v1','detail-single-round-cached-v1'}:
        if profile!='detail-only-v1':
            raise ValueError('Single-round detail requires the versioned detail-only rubric')
        binding['invocation_profile']=invocation
    measurement_spec=spec
    if profile=='detail-only-v1':
        measurement_spec=project_detail_spec(spec,visual_ids)
        spec_path=folder/'measurement_spec.json'
        if spec_path.exists() and read(spec_path)!=measurement_spec:
            raise ValueError('Cached detail measurement rubric changed')
        if not spec_path.exists():atomic(spec_path,measurement_spec)
        binding.update(measurement_profile=profile,measurement_spec=pin(spec_path))
    elif profile!='full-v1':
        raise ValueError('Unknown detail measurement profile: '+str(profile))
    if export_worker is not None:
        binding['export_worker']=pin(export_worker)
    output_name = 'detail.json' if selected_variants is None else 'screening.json'
    if allow_tracked_camera and (not (folder/output_name).exists()
            or 'export_fallback_worker' in read(folder/output_name).get('source_bindings',{})):
        binding['export_fallback_worker']=pin(ROOT/'src/evaluator/tracked_camera_export_blender.py')
    if allow_tracked_camera and (not (folder/output_name).exists()
            or 'export_light_fallback_worker' in read(folder/output_name).get('source_bindings',{})):
        binding['export_light_fallback_worker']=pin(ROOT/'src/evaluator/light_tracked_camera_export_blender.py')
    if allow_tracked_camera and (not (folder/output_name).exists()
            or 'export_animated_light_fallback_worker' in read(folder/output_name).get('source_bindings',{})):
        binding['export_animated_light_fallback_worker']=pin(ROOT/'src/evaluator/animated_light_export_blender.py')
    if (folder/output_name).exists():
        saved=read(folder/output_name)
        if saved['source_bindings']!=binding:raise ValueError('Cached detail evidence changed')
        if selected_variants is not None and saved.get('measured_variants') != measured_population:
            raise ValueError('Cached screening variant subset changed; use a separate output root')
        for pointer in saved.get('judge_runs',{}).values():
            pin(pointer['path'],pointer['sha256'])
        return saved
    task=Path(campaign['frozen'])/'data/3dbench/tasks'/task_id
    linear=read(root/'linear_config'/task_id/'rule.json')
    references=linear['reference_images']
    validate_published_references(spec, linear)
    variants=artifact_variants(run_dir,run,task_id.startswith('L1/'))
    if scoring_images:
        for seed,images in scoring_images['variants'].items():
            for name,pointer in images.items():pin(pointer['path'],pointer['sha256'])
            variants[seed]={**variants[seed],**images}
    config=compact_judge(replace(JudgeConfig.from_env(env_path()),model=judge_model(),effort='medium',
        api_key=judge_key(),
        base_url=campaign['provider_transport'],timeout=600))
    config=replace(config,
        responses_options={'max_rounds': int(os.environ.get('LEGACY_DETAIL_MAX_ROUNDS', '4')),
                           'request_attempts': int(os.environ.get('LEGACY_DETAIL_REQUEST_ATTEMPTS', '1')),
                           'max_output_tokens': int(os.environ.get('LEGACY_DETAIL_MAX_OUTPUT_TOKENS', '8000')),
                           'compact_tool_facts': True,
                           'preload_scenes': os.environ.get('LEGACY_DETAIL_PRELOAD_SCENES', '0') == '1',
                           'system_instructions': JUDGE_INSTRUCTIONS},
        inspection_guidance=('Use the supplied frozen checklist and read-only evidence. '
            'Inspect preloaded scene facts and attached authored images. Request only diagnostic '
            'views needed for unresolved requirements, batch independent views, and return the '
            'complete required schema with concise evidence.'))
    if invocation in {'detail-single-round-v1','detail-single-round-cached-v1'}:
        config=detail_single_round_judge(config)
        if invocation=='detail-single-round-cached-v1':
            config=replace(config,responses_options={**config.responses_options,
                            'response_cache':str((folder/'response_cache').resolve())})
    from tools.experiment_view_policy import load_views
    views, view_proof = load_views(root, task_id, recipe, measurement_spec)
    if view_proof is not None:
        # Keep the established detail binding for completed old results. New
        # paired evidence carries its additional policy/helper provenance here.
        atomic(folder/'view_policy_evidence.json', view_proof)
    scores={};provenance={};native_provenance={};preparation_failures={}
    atomic(folder/'status.json',{'status':'running','task_id':task_id,
        'required_variants':population,'measured_variants':measured_population})
    seed_locks={seed:Lock() for seed in {v.split('/',1)[0] for v in population}}
    def judge_variant(variant):
        seed,fmt=variant.split('/') if '/' in variant else (variant,'native')
        current=variants[seed];dest=folder/'variants'/variant
        native_results = {}
        if native_atoms:
            from tools.measure_interactive_detail import measure as mechanism
            mechanism_scene = current['scene.glb' if fmt=='glb' else 'scene.blend']
            for atom in native_atoms:
                native_results[atom['id']] = mechanism(mechanism_scene,
                    folder/'mechanism'/variant/atom['id'], atom['parameters'])
        try:
            # Shared seed preparation is serialized; judge calls remain parallel.
            with seed_locks[seed]:
                if task_id.startswith('L1/'):
                    native=collect_native(Path(current['scene.blend']['path']),folder/'native'/seed,detail_frame,
                        studio=row['category']=='Text2Code',main_required=True)
                    export_folder=folder/('export-keyframed' if export_worker else 'export')/seed
                    scene=exported_scene(current,native,export_folder,worker=export_worker,
                                         allow_tracked_camera=allow_tracked_camera) if fmt=='glb' else current['scene.blend']
                    rendered=collect_native(Path(scene['path']),dest/'render',detail_frame,studio=False,main_required=True) if fmt=='glb' else native
                    artifacts={'scene.blend':scene,**{k+'.png':{f:v[f] for f in ('path','sha256')} for k,v in rendered['renders'].items()}}
                    if task_id in views:
                        requested=[{**v,'image':str(dest/'paired'/v['id'])} for v in views[task_id]['views']]
                        paired=render(scene,requested,dest/'paired')
                        artifacts.update({k:v['image'] for k,v in paired['views'].items()})
                else:artifacts=dict(current)
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            from tools.recover_undefined_candidate import enabled
            message=str(error).lower()
            if not enabled() or any(word in message for word in ('changed','differs','binding','provenance','reference')):
                raise
            # Source bytes were accepted and are rechecked before assigning
            # zero only to visual criteria dependent on this preparation.
            for pointer in current.values(): pin(pointer['path'],pointer['sha256'])
            from src.evaluator.candidate_robustness import VERSION
            failure={'policy':VERSION,'variant':variant,'sources':current,
                'criterion_ids':visual_ids,'error_type':type(error).__name__,'reason':str(error),
                'scope':'Undefined candidate visual preparation; native kinematic credit retained', 'model_calls':0}
            atomic(dest/'preparation-zero.json',failure)
            criterion={identity:0. for identity in visual_ids}
            for identity,pointer in native_results.items(): criterion[identity]=read(Path(pointer['path']))['score']
            return variant,criterion,None,native_results,pin(dest/'preparation-zero.json')
        variant_config=config
        if invocation=='compact-v1' and os.environ.get('LEGACY_DETAIL_PRELOAD_NATIVE_VIEWS','0') == '1':
            preload=[{'scene':'candidate/scene.blend',
                      'purpose':'Preload one bound authored candidate render before the final schema response.'}]
            if plan.get('reference_target',{}).get('scene'):
                preload.append({'scene':'reference/scene.blend',
                    'purpose':'Preload one bound authored reference render before the final schema response.'})
            options=dict(config.responses_options)
            options['preload_views']=preload
            variant_config=replace(config,responses_options=options)
        result=judge_task(task,{'artifacts':artifacts,'reference_images':references},
            {'_vlm_judge':{'version':'continuous-task-judge-v1','spec':measurement_spec,
                'spec_sha256':binding.get('measurement_spec',binding['spec'])['sha256'],
                'mode':'interactive','edit_context':linear['edit_context']}},
            dest/'judge',config=variant_config,tested_model=tested_model(root),blender=BLENDER)
        criterion = dict(result.get('criterion_scores',{})) if result.get('status')=='scored' else {}
        for identity,pointer in native_results.items(): criterion[identity] = read(Path(pointer['path']))['score']
        return variant, criterion, pin(dest/'judge/run.json'), native_results, None
    workers=max(1,min(len(measured_population),int(os.environ.get(
        'LEGACY_DETAIL_VARIANT_WORKERS',str(campaign.get('detail_variant_workers',2))))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(judge_variant,variant) for variant in measured_population]
        for future in as_completed(futures):
            variant,criterion,provenance_row,native_results,preparation_failure=future.result()
            scores[variant]=criterion
            if provenance_row:provenance[variant]=provenance_row
            if native_results: native_provenance[variant]=native_results
            if preparation_failure: preparation_failures[variant]=preparation_failure
            atomic(folder/'status.json',{'status':'running','task_id':task_id,'finished_variants':list(scores),
                'required_variants':population,'measured_variants':measured_population,
                'variant_workers':workers})
    detail=detail_from_criteria(plan,recipe['criterion_ids'],scores,measured_population)
    if selected_variants is None:
        result={**detail,'source_bindings':binding,'judge_runs':provenance,
            'judge_model':judge_model(),'judge_effort':'medium',
            # Record the judged subset so finalize() replays the same arithmetic.
            # Equal to population unless LEGACY_DETAIL_VARIANT_LIMIT narrowed it.
            'required_variants':population,'measured_variants':measured_population}
        if native_provenance: result['native_runs']=native_provenance
        if preparation_failures: result['preparation_failures']=preparation_failures
        atomic(folder/'detail.json',result)
        atomic(folder/'status.json',{'status':detail['status'],'task_id':task_id})
    else:
        result={'status':'screening','measurement_status':detail['status'],
            'screening_score':detail['score'],
            'values_by_variant':detail['values_by_variant'],
            'required_variants':population,'measured_variants':measured_population,
            'criterion_ids':recipe['criterion_ids'],'source_bindings':binding,
            'judge_runs':provenance,'judge_model':judge_model(),'judge_effort':'medium'}
        atomic(folder/'screening.json',result)
        atomic(folder/'status.json',{'status':'screening','task_id':task_id,
            'required_variants':population,'measured_variants':measured_population})
    return result
