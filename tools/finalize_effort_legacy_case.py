"""Publish an ordinary v2 case only after baseline and full detail are bound."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from pathlib import Path

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from src.agent_judge.protocol import read_json as read

from src.evaluator.legacy_detail import replace_connection,detail_from_mixed_criteria as detail_from_criteria,require_full_population

from src.evaluator.legacy_detail_v2 import TASK_RULES,VERSION

from tools.evaluate_linear_candidate import pin,atomic

def finalize(root,task_id):
    if task_id in TASK_RULES:
        raise ValueError('This task requires the additional published v2 correction')
    name=Path(task_id).name
    base_path=root/'legacy_baseline'/tested_model(root)/'cases'/name/'report.json'
    from tools.recover_l1_strict_axes import verified_baseline_path
    base_path=verified_baseline_path(base_path)
    baseline=read(base_path);base_binding=pin(base_path)
    if baseline['task_id']!=task_id:raise ValueError('Baseline task mismatch')
    row=next(r for r in read(root/tested_model(root)/'batch.json')['cases'] if r['task_id']==task_id)
    if row['status'] in {'queued','running'}:raise ValueError('Generation is active')
    run=Path(row['run_dir'])
    if Path(baseline['source_run_dir']).resolve()!=run.resolve():raise ValueError('Candidate changed')
    if baseline.get('S_core') is None or type(baseline.get('score_valid')) is not bool:
        raise ValueError('Baseline measurement unresolved')
    for path,expected in baseline.get('source_bindings',{}).items():
        pin(path,expected)
    detail_path=root/'legacy_detail'/tested_model(root)/name/'detail.json'
    if baseline['score_valid'] is False and baseline['S_core']==0 and not detail_path.exists():
        atomic(detail_path,{'status':'not_measurable','score':None,
            'reason':'Confirmed invalid delivery; legacy validity gate retains zero',
            'source_bindings':{'run':pin(run/'run.json')},'judge_calls':0})
    detail=read(detail_path)
    if detail['source_bindings']['run']!=pin(run/'run.json'):
        raise ValueError('Detail belongs to another generation')
    if baseline['score_valid'] and detail.get('status')!='measured':
        raise ValueError('Required detail measurements incomplete')
    for binding in detail.get('judge_runs',{}).values():
        pin(binding['path'],binding['sha256'])
    if baseline['score_valid']:
        from tools.measure_effort_legacy_detail import contract
        recipe,plan,spec,population=contract(task_id,root)
        bindings=detail['source_bindings']
        if 'export_worker' in bindings:
            pin(bindings['export_worker']['path'],bindings['export_worker']['sha256'])
        for key in ('plan','spec'):
            pin(bindings[key]['path'],bindings[key]['sha256'])
        if bindings['plan']!=recipe['source_plan'] or bindings['variants']!=population:
            raise ValueError('Detail contract changed')
        if read(Path(bindings['spec']['path']))!=spec:raise ValueError('Detail rubric changed')
        projected=bindings.get('measurement_spec')
        if projected is not None:
            from src.agent_judge.detail_spec import project_detail_spec
            if bindings.get('measurement_profile')!='detail-only-v1':
                raise ValueError('Unknown detail measurement profile')
            pin(projected['path'],projected['sha256'])
            visual_ids=[c['id'] for c in recipe['criteria'] if c['method']=='visual_coverage_deviation']
            if read(Path(projected['path']))!=project_detail_spec(spec,visual_ids):
                raise ValueError('Projected detail criteria, weights or evidence changed')
        elif bindings.get('measurement_profile') is not None:
            raise ValueError('Detail measurement profile lacks its frozen rubric')
        require_full_population(detail, population)
        measured=population
        failures=detail.get('preparation_failures',{})
        if set(detail.get('judge_runs',{})) & set(failures): raise ValueError('Variant has both judge and preparation zero')
        if set(detail.get('judge_runs',{})) | set(failures) !=set(measured):
            raise ValueError('Detail judgment population incomplete')
        scores={}
        for variant,binding in detail['judge_runs'].items():
            judgment=read(Path(binding['path']))
            if judgment.get('status')!='scored':raise ValueError('Unaccepted detail judgment')
            if projected is not None and judgment.get('spec_sha256')!=projected['sha256']:
                raise ValueError('Detail judgment uses another measurement rubric')
            scores[variant]=dict(judgment.get('criterion_scores',{}))
        for variant,pointer in failures.items():
            from src.evaluator.candidate_robustness import VERSION as ROBUSTNESS
            from tools.evaluate_linear_candidate import artifact_variants
            pin(pointer['path'],pointer['sha256']); failure=read(Path(pointer['path']))
            seed,_=variant.split('/'); variants=artifact_variants(run,read(run/'run.json'),True)
            visual_ids=[c['id'] for c in recipe['criteria'] if c['method']=='visual_coverage_deviation']
            if (failure['policy']!=ROBUSTNESS or failure['sources']!=variants[seed]
                    or failure['variant']!=variant or failure['criterion_ids']!=visual_ids):
                raise ValueError('Preparation zero belongs to another candidate/rubric')
            for source in failure['sources'].values():pin(source['path'],source['sha256'])
            scores[variant]={identity:0. for identity in visual_ids}
        native_atoms=[c for c in recipe['criteria'] if c['method']!='visual_coverage_deviation']
        for variant in measured:
            if native_atoms:
                from tools.measure_interactive_detail import verify_result
                from tools.evaluate_linear_candidate import artifact_variants
                variants=artifact_variants(run,read(run/'run.json'),True)
                seed,fmt=variant.split('/')
                for atom in native_atoms:
                    pointer=detail['native_runs'][variant][atom['id']]
                    pin(pointer['path'],pointer['sha256']); measured_native=read(Path(pointer['path']))
                    scene=variants[seed]['scene.glb' if fmt=='glb' else 'scene.blend']
                    verify_result(measured_native,scene,atom['parameters'])
                    scores[variant][atom['id']]=measured_native['score']
        replay=detail_from_criteria(plan,recipe['criterion_ids'],scores,measured)
        for key in ('score','selected_variant','values_by_variant','criterion_ids'):
            if detail.get(key)!=replay.get(key):raise ValueError('Detail arithmetic or selection changed: '+key)
    record={'task_id':task_id,'model':tested_model(root),'effective_validity':baseline['score_valid'],
        'source_bindings':{'selected_report':base_binding}}
    report=replace_connection(baseline,detail,source_report=base_binding,
        detail_record=record,release_id=VERSION)
    report.update(scoring_version=VERSION,framework='legacy-composite-detail',
        components=report['score_components'],judge_model=judge_model(),judge_effort='medium',
        detail_source=pin(detail_path),baseline_report=base_binding)
    target=root/'main_results'/tested_model(root)/name/'report.json'
    if target.exists():
        old=read(target)
        if old!=report:raise ValueError('Refusing to replace a published case')
    else:atomic(target,report)
    return report
