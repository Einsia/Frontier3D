"""Measure legacy image/localization/VLM components on accepted new tasks.

This stage emits no task total: complete variant detail and system validity
are owned by the subsequent unified evaluator stages.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

import fcntl

from pathlib import Path

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig,judge_task

from src.agent_judge.protocol import read_json as read

from src.agent_judge.runtime import run_codex

from src.agent_judge.invocation_policy import compact_judge

from tools.evaluate_linear_candidate import atomic,pin

from tools.evaluate_new_task_legacy_v1 import measured_image

from tools.run_l1_strict_review import collect_native,BLENDER

from tools.run_new_tasks import jobdir,verify_task,record_call

from tools.watch_effort_historical import affected

def run(root,task_id,*,output_folder=None,judge_config=None):
    campaign=read(root/'campaign.json');row=next(r for r in campaign['records'] if r['task_id']==task_id)
    verify_task(root,row);source=jobdir(root,tested_model(root),task_id)
    generation=read(source/'generation_state.json')
    if generation['status']!='completed' or affected(source):raise ValueError('Clean accepted generation required')
    config_root=resource('addition_config')/Path(task_id).name
    plan=read(config_root/'plan.json');spec=read(config_root/'vlm_spec.json')
    for binding in [plan['rules'],plan['instruction'],*plan['references']]:pin(binding['path'],binding['sha256'])
    rules=read(Path(plan['rules']['path']));folder=Path(output_folder or source/'legacy_baseline');folder.mkdir(parents=True,exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        binding=pin(source/'generation_state.json')
        if (folder/'components.json').exists():
            saved=read(folder/'components.json')
            if saved['generation']!=binding:raise ValueError('Cached candidate changed')
            return saved
        artifacts={n:pin(Path(generation['output'])/n,h) for n,h in generation['artifact_sha256'].items()
            if n in {'scene.blend','main.png','alternate.png'}}
        scoring_path=source/'scene_scoring_evidence/images.json'
        if scoring_path.exists():
            from tools.scene_scoring_evidence import checked
            scoring=read(scoring_path)
            if scoring['source_variants']!=pin(source/'legacy_execution/variants.json'):
                raise ValueError('Scoring rerenders belong to another execution')
            artifacts={k:checked(v) for k,v in scoring['variants']['primary'].items()}
        if 'alternate.png' not in artifacts:
            # The hash-bound submitted main is already used below. Only collect
            # the missing reverse view here; primary consistency has its own
            # independent gate and must not be rendered twice in this stage.
            native=collect_native(Path(artifacts['scene.blend']['path']),folder/'native',1,
                                  studio=False,main_required='main.png' not in artifacts)
            artifacts['alternate.png']=pin(native['renders']['alternate']['path'],native['renders']['alternate']['sha256'])
        config=JudgeConfig(model=judge_model(),effort='medium',timeout=600,attempts=3,
            api_key=judge_key(),base_url=campaign['provider_url'],codex=campaign['codex'])
        config=judge_config or compact_judge(config,visual=True)
        def invoke(packet,directory,**kwargs):
            execution=run_codex(packet,directory,**kwargs)
            record_call(root,role='judge',model=config.model,tested_model=tested_model(root),task_id=task_id,directory=directory,execution=execution)
            return execution
        references={str(i):r for i,r in enumerate(plan['references'])}
        judgment=judge_task(Path(row['task_root']),{'artifacts':artifacts,'reference_images':references},
            {'_vlm_judge':{'version':'l2-vlm-judge-v2','spec':spec,'spec_sha256':pin(config_root/'vlm_spec.json')['sha256'],'mode':'visual'}},
            folder/'judge',config=config,tested_model=tested_model(root),blender=BLENDER,invoke=invoke)
        components={'vlm':judgment.get('S_vlm')}
        if plan['references']:
            image=measured_image(row,rules,plan['references'],artifacts)
            atomic(folder/'image_measurement.json',image)
            components.update(main_image=image.get('score'),localization=judgment.get('localization',{}).get('score'))
        else:components['data']=None
        report={'task_id':task_id,'generation':binding,'plan':pin(config_root/'plan.json'),
            'components':components,'S_core':None,'status':'baseline_components_only',
            'images':artifacts,'judge':pin(folder/'judge/run.json'),
            'remaining':['system validity','complete detail variants']+([] if plan['references'] else ['native content']),
            'new_candidate_generations':0}
        if scoring_path.exists():report['scoring_evidence']=pin(scoring_path)
        atomic(folder/'components.json',report);return report
