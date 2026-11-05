"""Collect hash-bound read-only reference-image usage evidence."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import os

from pathlib import Path

import subprocess

from tools.bench_control import load,atomic

from tools.bench_repair_timer import mkdir

from tools.evaluate_linear_candidate import pin

from tools.run_l1_strict_review import BLENDER

ROOT=Path(__file__).resolve().parents[1]

def collect(scene,references,folder):
    folder=folder/'v3';mkdir(folder);worker=ROOT/'src/evaluator/reference_texture_usage_v3_blender.py'
    request=folder/'request.json';output=folder/'result.json'
    pin(scene['path'],scene['sha256'])
    if not output.exists():
        atomic(request,dict(scene=scene,reference_sha256=sorted(references),output=str(output)))
        with (folder/'worker.log').open('w') as log:
            subprocess.run([str(BLENDER),'-b','--factory-startup','--disable-autoexec','--threads','2',
                '--python-exit-code','1','--python',str(worker),'--',str(request)],
                stdout=log,stderr=log,timeout=180,check=True,
                env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2'})
    result=load(output)
    if result['scene']!=scene or set(result['reference_sha256'])!=set(references):
        raise ValueError('Reference usage scene/reference binding changed')
    pin(worker,result['worker_sha256']);pin(request,result['request_sha256'])
    if not result['source_unchanged']:raise ValueError('Reference source scene changed')
    return result,pin(output)
