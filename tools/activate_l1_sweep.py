"""Prepare the Text2Code reference and print the corresponding task-spec configuration."""

import argparse

import copy

import difflib

import json

import shutil

import sys

from pathlib import Path

PROJECT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(PROJECT))

from orchestrator.tasks import sha256

from src.evaluator.l1_seed_quality import MEASUREMENTS

TASK=PROJECT/'data/3dbench/tasks/L1/Text2Code/task_L1_Text2Code_014'

FEATURES=('solid','surface','section_dimensions')

def expand(raw, reference_sha256):
    spec=copy.deepcopy(raw)
    design={'width_m':.0093,'depth_m':.0069,'tolerance_m':.00015,
        'reference_path':'harness/sweep_reference/reference_v1.json','reference_sha256':reference_sha256}
    additions=[]
    for prefix,scene in [('native','/scene'),('glb','/artifacts/scene.glb/scene')]:
        for feature in FEATURES:
            additions.append({'id':f'{prefix}_sweep_{feature}','metric':'swept_bar','group':'sweep_'+feature,
                'params':{'path':f'/numeric_checks/{prefix}_sweep','scene':scene,'design':design,'feature':feature},
                'pass_threshold':1.0})
    ids={c['id'] for c in additions}
    spec['checks']['geometry']=[c for c in spec['checks']['geometry'] if c['id'] not in ids]+additions
    spec['critical_constraints']=sorted(set(spec['critical_constraints'])|ids)
    surface=['native_sweep_surface','glb_sweep_surface']
    sections=['native_sweep_section_dimensions','glb_sweep_section_dimensions']
    for row in spec['l1_protocol']['requirements']:
        if row['id'] in {'interpolated_path','sweep_transport','surface_accuracy','rectangular_section','units'}:
            row['implementation']='partial'
            row['check_ids']=sorted(set(row['check_ids'])|set(surface+sections))
            row['reason']='已接原生/GLB连续双向表面误差及25个明确矩形切面尺寸；紧弯5切面不强加矩形，全部路径尺寸/特征与容差标定仍待完成，不提升整题验收。'
        if row['id']=='editable_part':
            row['check_ids']=sorted(set(row['check_ids'])|{'native_sweep_solid','glb_sweep_solid'})
    selected=sorted(c['id'] for group in spec['checks'].values() for c in group if c['metric'] in MEASUREMENTS)
    for group in spec['checks'].values():
        for check in group:
            if check['metric']=='all_seed_checks':
                check['params']['checks']=selected
    return spec
