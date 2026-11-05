"""Retain all seed executions of an accepted new-task candidate; no model calls."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

import fcntl

from pathlib import Path

import sys

import time

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from src.agent_judge.protocol import read_json as read

from orchestrator.tasks import load_task

from orchestrator.runner import execute

from tools.evaluate_linear_candidate import atomic,pin

from tools.watch_effort_historical import affected

from tools.run_new_tasks import verify_task,jobdir

def run(root,task_id):
    campaign=read(root/'campaign.json')
    row=next(r for r in campaign['records'] if r['task_id']==task_id)
    verify_task(root,row)
    original=jobdir(root,tested_model(root),task_id)
    generation_path=original/'generation_state.json';generation=read(generation_path)
    if generation['status']!='completed':raise ValueError('Accepted generation required')
    if affected(original):raise ValueError('Environment recovery required first')
    folder=original/'legacy_execution';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        binding=pin(generation_path)
        for name,expected in generation['source_sha256'].items():pin(Path(generation['source'])/name,expected)
        primary={name:pin(Path(generation['output'])/name,sha) for name,sha in generation['artifact_sha256'].items()}
        manifest_path=folder/'variants.json'
        if manifest_path.exists():
            manifest=read(manifest_path)
            if manifest['generation']!=binding:raise ValueError('Variant generation binding changed')
        else:manifest={'task_id':task_id,'generation':binding,'status':'running','variants':{'primary':primary},'executions':{}}
        task=load_task(task_id,root/'tasks',require_harness=False)
        for seed in (0,1,2):
            name='seed-'+str(seed);destination=folder/name
            if (destination/'attempts.json').exists():
                attempts=read(destination/'attempts.json')
            else:
                atomic(manifest_path,manifest)
                attempts=execute(task,Path(generation['source']),generation['source_sha256'],destination,
                    blender=Path(campaign['blender']),runtime=os.environ.get('THREEDBENCH_RUNTIME','docker'),image=os.environ.get('THREEDBENCH_IMAGE','3dbench-l1-blender:mvp'),
                    seed=seed,attempts=1,deadline=time.monotonic()+campaign['execution_timeout']+30,
                    attempt_timeout=campaign['execution_timeout'])
            if not attempts:raise ValueError('Empty execution history')
            execution=attempts[-1];manifest['executions'][name]=execution
            if execution['status']=='success':
                output=Path(execution['workspace'])/'output'
                manifest['variants'][name]={n:pin(output/n,h) for n,h in execution['artifact_sha256'].items()}
            atomic(manifest_path,manifest)
        manifest['status']='completed' if len(manifest['variants'])==4 else 'execution_incomplete'
        manifest['new_model_calls']=0
        atomic(manifest_path,manifest)
        return manifest
