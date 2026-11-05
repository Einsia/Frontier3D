"""Consolidate source-bound L3 evidence without turning missing evidence into scores."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.report_l3_runtime import report as runtime_report
from harness.L3.MinecraftVillage.protocol import REQUIRED, read_json, write_json, digest, tree_digest
from harness.L3.MinecraftVillage.evaluate import journey_diagnostics

def optional(path):
    return read_json(path) if path.exists() else None

def count_checks(checks):
    return {'passed':sum(v is True for v in checks.values()),
            'failed':sum(v is False for v in checks.values()),
            'unresolved':sum(v is None for v in checks.values()),'total':len(checks)}

def report(trial, run=None, rubric_dir=None):
    run=run or trial/'verification'
    rubric_dir=rubric_dir or trial/'rubrics'
    generation=read_json(trial/'trial.json')
    verification=optional(run/'run.json') or {}
    if verification:
        if verification.get('source_sha256')!=tree_digest(trial/'workspace/project'):
            raise ValueError('Verification source does not match candidate')
        for rel,expected in verification.get('evidence_sha256',{}).items():
            path=run/rel
            if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()) or digest(path)!=expected:
                raise ValueError('Verification evidence changed: '+rel)
    geometry=optional(run/'geometry.json')
    reference=optional(run/'reference.json')
    rubrics=optional(rubric_dir/'summary.json')
    if rubrics:
        if rubrics.get('source_sha256')!=verification.get('source_sha256'):
            raise ValueError('Rubrics refer to a different candidate')
        for rel,expected in rubrics.get('frozen_image_hashes',{}).items():
            path=run/rel
            if path.is_symlink() or not path.resolve().is_relative_to(run.resolve()) or digest(path)!=expected:
                raise ValueError('Rubric image changed: '+rel)
    interactions={}
    for target in REQUIRED:
        key=target.replace('.','_')
        episode=verification.get('episodes',{}).get(key,{})
        failure=verification.get('submission_contract_failures',{}).get(key)
        diagnostics=episode.get('diagnostics',{})
        checks=diagnostics.get('checks',{})
        counts=count_checks(checks)
        interactions[target]={
            'status':'submission_contract_failure' if failure or diagnostics.get('status')=='submission_contract_failure'
                      else 'measured' if episode.get('completed') and checks else 'not_measured',
            'contract_failure':failure or (diagnostics if diagnostics.get('status')=='submission_contract_failure' else None),
            'geometry_and_action_checks':checks,'check_counts':counts,
            'inventory':episode.get('inventory'),'formal_score':None}
    journey=None
    if verification.get('episodes',{}).get('journey',{}).get('completed'):
        journey=journey_diagnostics(run/'workspace/episodes/journey')
    return {
        'schema_version':1,'trial':str(trial),'model':generation.get('model'),
        'generation':runtime_report(trial),'completion_evidence':generation.get('completion_evidence'),
        'verification_path':str(run),'rubric_path':str(rubric_dir),
        'verification_status':verification.get('status','not_started'),'verification_error':verification.get('error'),
        'deterministic':{
            'layout':{'status':'measured_diagnostics' if geometry else 'not_measured','measurements':geometry,
                      'journey':journey,'formal_score':None,
                      'limitation':'Raw solid overlaps are not automatically illegal intersections; assembly rules and support semantics require calibration.'},
            'interaction':{'targets':interactions,
                           'resource_bearing_local_chain':optional(run/'resource-chain.json') or {'status':'not_measured'},
                           'continuous_workflow':optional(run/'workflow.json') or {'status':'not_measured','reason':'No validated continuous on-foot route evidence','formal_score':None},
                           'formal_score':None},
            'reference_accuracy':reference or {'status':'not_measured','formal_score':None}},
        'rubrics':rubrics or {'status':'not_measured','score':None},
        'material_usage':optional(run/'asset-usage.json'),
        'weights':None,'formal_score':None,
        'limitations':['Reference annotation validation and cross-level score calibration are required before leaderboard aggregation.',
                       'A failed contract, a failed measured assertion and an unavailable measurement are distinct outcomes.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--trial',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--verification-run',type=Path);p.add_argument('--rubric-dir',type=Path)
    a=p.parse_args();write_json(a.output,report(a.trial.resolve(),a.verification_run.resolve() if a.verification_run else None,a.rubric_dir.resolve() if a.rubric_dir else None))
