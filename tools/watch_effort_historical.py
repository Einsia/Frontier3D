"""Dispatch terminal historical candidates through the legacy-detail v2 stages."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from concurrent.futures import ThreadPoolExecutor

import fcntl

import json

from pathlib import Path

import subprocess

import sys

import time

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from src.agent_judge.protocol import read_json as read

from src.evaluator.legacy_detail_v2 import TASK_RULES

from tools.evaluate_linear_candidate import atomic

def affected(run):
    for path in run.glob('generation-*/process/*.log'):
        data=path.read_bytes()
        if b'No permissions to create a new namespace' in data or b'bwrap: Creating new namespace failed' in data:
            return True
    return False

def worker(root,task):
    from tools.bind_effort_codeedit import bind
    from tools.run_effort_l1_baseline import run as l1
    from tools.run_effort_l2_baseline import run as l2
    from tools.measure_effort_legacy_detail import measure
    from tools.finalize_effort_legacy_case import finalize
    from tools.correct_effort_legacy_v2 import correct
    row=next(r for r in read(root/tested_model(root)/'batch.json')['cases'] if r['task_id']==task)
    if row['status'] in {'running','queued'}:raise ValueError('Generation is not terminal')
    if affected(Path(row['run_dir'])):raise ValueError('Environment recovery required before evaluation')
    if row['category']=='CodeEdit':return bind(root,task)
    name=Path(task).name;base=root/'legacy_baseline'/tested_model(root)/'cases'/name/'report.json'
    detail=root/'legacy_detail'/tested_model(root)/name/'detail.json'
    # Completed measurements can still be checked while new paid calls are gated.
    if base.exists() and detail.exists() and read(detail).get('status')=='measured' and task not in TASK_RULES:
        return finalize(root,task)
    gate=root.parent/'judge_runtime_gate.json'
    if gate.exists() and read(gate).get('allow_new_default_judge_calls') is not True:
        raise ValueError('New default judge calls held by judge_runtime_gate.json; cost validation required')
    if not base.exists():
        (l1 if task.startswith('L1/') else l2)(root,task)
    from tools.recover_l1_strict_axes import verified_baseline_path
    from tools.recover_candidate_content_partial import recover_if_confirmed
    if read(base).get('S_core') is None and not base.with_name('candidate_partial_report.json').exists():
        recover_if_confirmed(base)
    base=verified_baseline_path(base)
    baseline=read(base)
    if baseline.get('S_core') is None:
        from tools.recover_undefined_candidate import enabled, recover
        if enabled():
            baseline = recover(base)
            base = base.with_name('robustness_report.json')
    if baseline.get('S_core') is None:raise ValueError('Baseline measurements unresolved')
    if task in TASK_RULES:return correct(root,task)
    export_worker=ROOT/'src/evaluator/keyframed_camera_export_blender.py' if task.startswith('L1/') else None
    if baseline.get('score_valid') is True:
        measure(root,task,export_worker=export_worker,allow_tracked_camera=task.startswith('L1/'))
    return finalize(root,task)
