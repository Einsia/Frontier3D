"""Audited native evidence plus explicitly scoped visual diagnostics for new tasks."""

from __future__ import annotations

import os

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from dataclasses import replace

import json

import os

from pathlib import Path

import re

import subprocess

import sys

import time

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

import numpy as np

from PIL import Image

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig,judge_task

from src.agent_judge.runtime import run_codex

from src.run_usage import parse_events

from orchestrator.tasks import load_task,sha256,write_json

from orchestrator.runner import execute

from tools.run_new_tasks import read, now, jobdir, record_call, verify_task

def pin(path,expected=None):
    path=Path(path).resolve(strict=True);value=sha256(path)
    if expected is not None and value!=expected:raise ValueError('Bound evidence changed: '+str(path))
    return {'path':str(path),'sha256':value}

def worker(campaign,scene,folder,*,inspect_only,level):
    folder.mkdir(parents=True,exist_ok=True)
    script=ROOT/'src/evaluator/new_task_audit_blender.py'
    request={'scene':scene,'output':str(folder),'inspect_only':inspect_only,'level':level}
    if (folder/'result.json').exists():
        cached=read(folder/'result.json')
        if (read(folder/'request.json')!=request or cached['worker_sha256']!=sha256(script)
                or cached['request_sha256']!=sha256(folder/'request.json')):raise ValueError('Audit cache changed')
        if inspect_only:
            for snapshot in cached['result']['snapshots']:
                for obj in snapshot['objects']:
                    if obj.get('geometry'):pin(obj['geometry']['path'],obj['geometry']['sha256'])
        else:
            for image in cached['result']['renders'].values():pin(image['path'],image['sha256'])
            if cached['result'].get('alternate'):
                image=cached['result']['alternate'];pin(image['path'],image['sha256'])
        return cached['result']
    write_json(folder/'request.json',request)
    environment={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL'}}
    environment.update(OMP_NUM_THREADS='4',OPENBLAS_NUM_THREADS='2')
    with (folder/'worker.log').open('w') as stream:
        process=subprocess.run([campaign['blender'],'-b','--factory-startup','--disable-autoexec','--threads','4','--python-exit-code','1','--python',str(script),'--',str(folder/'request.json')],stdout=stream,stderr=subprocess.STDOUT,env=environment,timeout=1200)
    if process.returncode!=0:raise ValueError('Native audit failed; see '+str(folder/'worker.log'))
    pin(scene['path'],scene['sha256'])
    return read(folder/'result.json')['result']

def geometry_summary(native):
    snapshot=native['snapshots'][0]
    objects=[o for o in snapshot['objects'] if o.get('geometry')]
    if objects:
        bounds=np.asarray([o['bounds_m'] for o in objects]);low=bounds[:,0].min(0);high=bounds[:,1].max(0)
        spans=(high-low).tolist()
    else:low=high=None;spans=None
    return {'objects':len(objects),'triangles':snapshot['triangles'],'all_geometry_editable':all(o['editable'] for o in objects) if objects else False,
        'bounds_m':[low.tolist(),high.tolist()] if objects else None,'span_m':spans,'max_span_m':max(spans) if spans else None,
        'cameras':[{'name':o['object'],'matrix_world_m':o['matrix_world_m'],'settings':o['settings']} for o in snapshot['objects'] if o['type']=='CAMERA'],
        'render':snapshot['render'],'unit_scale':snapshot['unit_scale'],'unit_system':snapshot['unit_system']}
