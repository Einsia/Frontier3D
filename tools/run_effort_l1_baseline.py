"""Measure a terminal effort candidate with the published L1 legacy baseline.

These reports are intermediate measurements. Detail replacement and the four
v2 corrections must finish before publishing the final legacy-detail v2 score.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from dataclasses import replace

import fcntl

import json

from pathlib import Path

import shutil

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig

from src.agent_judge.invocation_policy import configured_judge

from orchestrator.tasks import sha256,write_json

from tools.run_l1_strict_review import review_one

def prepare(root):
    source=resource('l1_plans')
    output=root/'legacy_baseline';output.mkdir(parents=True,exist_ok=True)
    lease=output/'.prepare.lock';handle=lease.open('a');fcntl.flock(handle,fcntl.LOCK_EX)
    frozen=Path(json.loads((root/'campaign.json').read_text())['frozen'])
    bindings={}
    for file in sorted(source.rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(source)
        target=output/'plans'/relative
        if target.exists() and sha256(target)!=sha256(file):
            raise ValueError('Baseline rule changed: '+str(relative))
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():shutil.copyfile(file,target)
        bindings[str(relative)]=sha256(target)
        if file.name=='alignment.json':
            plan=json.loads(file.read_text())
            for name,expected in plan['sources'].items():
                path=frozen/'data/3dbench/tasks'/plan['task_id']/name
                if sha256(path)!=expected:raise ValueError('Published baseline input differs: '+str(path))
    manifest=output/'plans_manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())['files']!=bindings:
        raise ValueError('Baseline manifest changed')
    write_json(manifest,{'source':str(source),'files':bindings})
    return output

def run(root,task):
    output=prepare(root)
    row=next(r for r in json.loads((root/tested_model(root)/'batch.json').read_text())['cases'] if r['task_id']==task)
    if not task.startswith('L1/') or row['status'] in {'queued','running'}:
        raise ValueError('A terminal L1 generation is required')
    campaign=json.loads((root/'campaign.json').read_text())
    config=replace(JudgeConfig.from_env(env_path()),model=judge_model(),effort='medium',
        api_key=judge_key(),
        base_url=campaign['provider_transport'],timeout=600,attempts=3)
    result=review_one(root,output,tested_model(root),row,configured_judge(config,campaign))
    return {k:result.get(k) for k in ('task_id','status','S_core','error')}
