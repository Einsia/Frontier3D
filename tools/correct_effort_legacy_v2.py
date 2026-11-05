"""Apply the published four-task v2 correction to fresh bound candidates."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from dataclasses import replace

import fcntl

import math

from pathlib import Path

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig,judge_task

from src.agent_judge.invocation_policy import configured_judge

from src.agent_judge.protocol import read_json as read

from src.evaluator.legacy_detail import ratio

from src.evaluator.legacy_detail_v2 import VERSION,REVISION,TASK_RULES,linear_observations,component_scores

from tools.evaluate_linear_candidate import atomic,pin

from tools.run_l1_strict_review import BLENDER

def correct(root,task_id,*,publish=True):
    if task_id not in TASK_RULES:raise ValueError('Task has no published v2 correction')
    folder=root/'legacy_v2'/tested_model(root)/Path(task_id).name
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _correct(root,task_id,folder,publish=publish)

def _correct(root,task_id,folder,*,publish=True):
    base_path=root/'legacy_baseline'/tested_model(root)/'cases'/Path(task_id).name/'report.json'
    baseline=read(base_path)
    if baseline['task_id']!=task_id or type(baseline.get('score_valid')) is not bool:
        raise ValueError('Baseline identity/validity unresolved')
    for path,expected in baseline.get('source_bindings',{}).items():pin(path,expected)
    row=next(r for r in read(root/tested_model(root)/'batch.json')['cases'] if r['task_id']==task_id)
    if row['status'] in {'queued','running'}:raise ValueError('Generation still active')
    run=Path(row['run_dir'])
    if Path(baseline['source_run_dir']).resolve()!=run.resolve():raise ValueError('Baseline candidate changed')
    source=resource('v2_root')
    inputs=read(source/'inputs.json')
    pointers=[j['spec'] for j in inputs['jobs'] if j['task_id']==task_id]
    if not pointers or any(p!=pointers[0] for p in pointers):raise ValueError('Ambiguous published v2 rule')
    spec_binding=pin(pointers[0]['path'],pointers[0]['sha256']);spec=read(Path(spec_binding['path']))
    weights={'main_image':.5,'localization':.2,'vlm':.2,'detail':.1}
    components={k:None for k in weights};judgment={};score=0.
    if baseline['score_valid']:
        components['localization']=ratio(baseline['score_components']['localization'])
        artifacts=baseline.get('review_images')
        if not artifacts:
            record=read(run/'execution_record.json')
            artifacts={name:pin(run/'submission'/name,sha) for name,sha in record['artifact_sha256'].items()
                if name in {'scene.blend','main.png','alternate.png'}}
        for item in artifacts.values():pin(item['path'],item['sha256'])
        refs=read(root/'linear_config'/task_id/'rule.json')['reference_images']
        for name,expected in spec['reference_bindings'].items():pin(refs[name]['path'],expected)
        campaign=read(root/'campaign.json');task=Path(campaign['frozen'])/'data/3dbench/tasks'/task_id
        config=replace(JudgeConfig.from_env(env_path()),model=judge_model(),effort='medium',
            api_key=judge_key(),base_url=campaign['provider_transport'],
            timeout=600,attempts=3)
        atomic(folder/'status.json',{'status':'running','task_id':task_id})
        judgment=judge_task(task,{'artifacts':artifacts,'reference_images':refs},
            {'_vlm_judge':{'version':'continuous-task-judge-v1','spec':spec,
                'spec_sha256':spec_binding['sha256'],'mode':'interactive','edit_context':{}}},
            folder/'judge',config=configured_judge(config,campaign),tested_model=tested_model(root),blender=BLENDER)
        if judgment.get('status')!='scored':
            atomic(folder/'status.json',{'status':'not_measurable','task_id':task_id})
            return {'status':'not_measurable','S_core':None}
        components.update(component_scores(task_id,linear_observations(task_id,judgment['criteria'])))
        score=math.fsum(weights[k]*components[k] for k in weights)
    report={**baseline,'scoring_version':VERSION,'framework':'legacy-composite-detail',
        'release_id':VERSION,'method_version':VERSION+'/'+row['category'],'scoring_revision':REVISION,
        'S_core':score,'S_level':score,'components':components,'component_weights':weights,
        'score_components':{**components,**{k+'_weight':v for k,v in weights.items()}},
        'status':'scored' if baseline['score_valid'] else 'system_invalid',
        'baseline_report':pin(base_path),'v2_spec':spec_binding,
        'v2_judgment':pin(folder/'judge/run.json') if judgment else None,
        'preserved_components':['localization'],'judge_model':judge_model(),'judge_effort':'medium'}
    target=root/'main_results'/tested_model(root)/Path(task_id).name/'report.json'
    if not publish:
        return report
    if target.exists() and read(target)!=report:raise ValueError('Refusing to replace published correction')
    atomic(target,report);atomic(folder/'status.json',{'status':report['status'],'S_core':score})
    return report
