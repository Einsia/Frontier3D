"""Durable generation-first runner for an explicit frozen task inventory."""

from __future__ import annotations
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from concurrent.futures import ThreadPoolExecutor, as_completed

from dataclasses import replace

from datetime import datetime, timezone

import fcntl

import hashlib

import json

import os

import queue

from pathlib import Path

import shutil

import subprocess

import sys

import time

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from orchestrator.generator import generate

from orchestrator.runner import execute, snapshot

from orchestrator.tasks import load_task, sha256, write_json

from src.generator.client import GeneratorConfig

from src.run_usage import estimate_cost,with_archived_usage

from tools.export_task_usage import summarize_calls

def read(path): return json.loads(Path(path).read_text())

def now(): return datetime.now(timezone.utc).isoformat()

def jobdir(batch,model,task_id): return batch/'runs'/model/Path(task_id).name

def record_call(batch, *, role, model, tested_model, task_id, directory, execution,inline_recorded=True,recovery=None):
    """Called by the generation/judge lifecycle, including failed attempts."""
    if not execution.get('usage_coverage'):
        execution=with_archived_usage(directory,execution,expected_model=model)
    identity=str(directory.resolve().relative_to(batch))
    identifier=hashlib.sha256(identity.encode()).hexdigest()
    usage=execution.get('usage')
    record={'id':identifier,'attempt_path':identity,'role':role,'model':model,
        'tested_model':tested_model,'task_id':task_id,'recorded_utc':now(),
        'usage':usage,'session_ids':execution.get('session_ids',[]),
        'status':execution.get('status'),'usage_known':usage is not None,
        'usage_coverage':execution['usage_coverage'],'usage_provenance':execution.get('usage_provenance'),
        'seconds':execution.get('seconds',execution.get('elapsed_seconds',execution.get('execution',{}).get('elapsed_seconds'))),
        'cost':estimate_cost(usage,model,read(batch/'pricing.json')),
        'actual_charge':False,'inline_recorded':inline_recorded}
    if recovery is not None:record['recording_recovery']=recovery
    write_json(directory/'api_usage.json',record)
    write_json(batch/'usage/calls'/f'{identifier}.json',record)
    return record

def verify_task(batch,row):
    campaign=read(batch/'campaign.json')
    if sha256(batch/'task_bindings.json')!=campaign['task_bindings_sha256']:raise ValueError('Task binding manifest changed')
    bindings=read(batch/'task_bindings.json')
    prefix='tasks/'+row['task_id']+'/'
    for name,expected in bindings.items():
        if name.startswith(prefix) or name==str(Path(row['rule']).relative_to(batch)):
            if sha256(batch/name)!=expected:raise ValueError('Frozen task changed: '+name)
