"""Complete deferred L2 baseline judgments without regenerating candidates."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from dataclasses import replace

import fcntl

from pathlib import Path

import sys

ROOT=Path(__file__).resolve().parents[1]

sys.path.insert(0,str(ROOT))

from tools.experiment_identity import tested_model

from dotenv import dotenv_values

from harness.L2.vlm_judge import JudgeConfig

from src.agent_judge.invocation_policy import compact_judge, configured_judge

from src.agent_judge.protocol import read_json as read

from tools.evaluate_linear_candidate import atomic,pin

from tools.rescore_l2_vlm import rescore

from tools.run_l1_strict_review import BLENDER

def run(root,task_id,*,preview=False,output_folder=None):
    row=next(r for r in read(root/tested_model(root)/'batch.json')['cases'] if r['task_id']==task_id)
    if not task_id.startswith('L2/') or row['status'] in {'queued','running'}:
        raise ValueError('Terminal L2 candidate required')
    source=Path(row['run_dir']);original=read(source/'run.json')
    campaign=read(root/'campaign.json');task=Path(campaign['frozen'])/'data/3dbench/tasks'/task_id
    for key in ('task_id','spec_sha256'):
        if original[key]!=row[key]:raise ValueError('Generation task binding changed')
    pin(task/'instruction.md',row['instruction_sha256'])
    published=next(t for t in read_public_methods() if t['id']==task_id)
    expected=published['method_version']
    folder=Path(output_folder or root/'legacy_baseline'/tested_model(root)/'cases'/Path(task_id).name)
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        generation_origin = None
        if original.get('model_call') is not True:
            provenance = row.get('previous_row', {}).get('source_provenance', {})
            generation_origin = Path(provenance['source_run_dir'])
            pin(generation_origin/'run.json', provenance['source_run_sha256'])
        config=replace(JudgeConfig.from_env(env_path()),model=judge_model(),effort='medium',
            api_key=judge_key(),
            base_url=campaign['provider_transport'],timeout=600,attempts=3)
        config=compact_judge(config,preview=True) if preview else configured_judge(config,campaign)
        report_path, evidence_path = original['report_path'], original['evidence_path']
        audits = [read(source/'audit'/(label+'.json')) for label in ('baseline','seed-0','seed-1','seed-2')]
        from src.evaluator.content_evidence_policy import l2_audit_valid
        policy_needed=(original.get('implementation_unchanged') is False or any(
            a.get('reproduction_matches_baseline') is False or a.get('rerender',{}).get('passed') is False for a in audits))
        use_rerender=any(a.get('rerender',{}).get('passed') is False for a in audits)
        if policy_needed and all(l2_audit_valid(a) for a in audits):
            from tools.reassess_scene_content import prepare
            request=folder/'content_reassessment_request.json'
            retained=read(request)['retained_report'] if request.exists() else None
            report_path,evidence_path=prepare(task,source,folder/'content-reassessment',retained_report=retained,rerender=use_rerender)
        report=rescore(task,source,folder/'raw',config=config,blender=BLENDER,
            report_path=report_path,evidence_path=evidence_path,timeout=2400,
            generation_source_run=generation_origin)
        if report['method_version']!=expected:raise ValueError('Baseline does not match published L2 method')
        report={**report,'source_run_dir':str(source.resolve())}
        if policy_needed and all(l2_audit_valid(a) for a in audits):
            report['scoring_policy_revision']='content-partial-rerender-20261103-v1'
            report['evidence_path']=str(evidence_path)
            report['content_policy_receipt']=pin(folder/'content-reassessment/policy-receipt.json')
            report['source_bindings'][str(folder/'content-reassessment/policy-receipt.json')]=report['content_policy_receipt']['sha256']
            if use_rerender:
                report['scoring_images']=pin(folder/'content-reassessment/render-evidence/images.json')
                report['source_bindings'][report['scoring_images']['path']]=report['scoring_images']['sha256']
        report['source_bindings'][str(source/'run.json')]=pin(source/'run.json')['sha256']
        atomic(folder/'report.json',report)
        return report
