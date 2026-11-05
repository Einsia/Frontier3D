"""Bind unchanged CodeEdit measurements into the legacy-detail v2 release.

CodeEdit retains its original numeric/target/preservation evaluator in v2.
This command verifies native artifacts and provenance without model calls.
Other task categories require their separate legacy measurement stages.
"""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

import json

import math

from pathlib import Path

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from tools.run_l1_strict_review import review_one

from harness.L2.vlm_judge import JudgeConfig

from src.evaluator.legacy_detail import legacy_weights

from orchestrator.tasks import sha256,write_json

def bind(root,task_id=None):
    reference={'tasks': read_public_methods()}
    tasks={t['id']:t for t in reference['tasks']}
    batch=json.loads((root/tested_model(root)/'batch.json').read_text())
    results=[]
    for row in batch['cases']:
        if task_id is not None and row['task_id']!=task_id:continue
        if row['category']!='CodeEdit' or row['status'] in {'queued','running'}:continue
        task=tasks[row['task_id']]
        if any(row[k]!=task[k] for k in ('spec_sha256','instruction_sha256')):
            raise ValueError('Published task binding differs')
        path=root/'main_results'/tested_model(root)/Path(row['task_id']).name/'report.json'
        if path.exists():continue
        base=review_one(root,root/'legacy_baseline',tested_model(root),row,JudgeConfig(model=judge_model(),effort='medium'))
        source=root/'legacy_baseline'/tested_model(root)/'cases'/Path(row['task_id']).name/'report.json'
        from tools.recover_l1_strict_axes import verified_baseline_path
        selected = verified_baseline_path(source)
        if selected != source: base=json.loads(selected.read_text())
        if base.get('S_core') is None:
            from tools.recover_undefined_candidate import enabled, recover
            if enabled():
                base=recover(source)
                selected=source.with_name('robustness_report.json')
        score=base.get('S_core')
        if score is None:
            results.append({'task_id':row['task_id'],'status':'pending_measurement'})
            continue
        expected=task['method_version']
        if base.get('method_version')!=expected:raise ValueError('CodeEdit method differs')
        weights={'numeric':.4,'target':.4,'preservation':.2}
        components=base.get('score_components',{})
        if base.get('score_valid') is True:
            if legacy_weights(base)!=weights:
                raise ValueError('CodeEdit weights differ')
            value=math.fsum(weights[k]*components[k] for k in weights)
            if not math.isclose(value,score,abs_tol=1e-8):raise ValueError('CodeEdit arithmetic differs')
        elif base.get('score_valid') is not False or score!=0:
            raise ValueError('Invalid CodeEdit zero binding')
        source=selected
        report={**base,'framework':'legacy-composite-detail',
            'scoring_version':'legacy-detail-20261019-v2',
            'status':'scored' if base.get('score_valid') else 'system_invalid',
            'components':components,'component_weights':weights,
            'baseline_report':{'path':str(source.resolve()),'sha256':sha256(source)},
            'judge_model':judge_model(),'judge_effort':'medium','judge_calls':0,
            'judge_not_required_reason':'CodeEdit method is unchanged in legacy-detail v2'}
        write_json(path,report)
        results.append({'task_id':row['task_id'],'status':report['status'],'score':score})
    return results
