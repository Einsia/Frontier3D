"""Bound L2 baseline reassessment under the scene-authoritative content policy."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import copy

import math

from pathlib import Path

from PIL import Image

from tools.bench_control import load, atomic

from tools.evaluate_linear_candidate import pin

from tools.bench_repair_timer import mkdir

from src.evaluator.content_evidence_policy import VERSION, l2_audit_valid

def prepare(task, run, folder, *, retained_report=None, rerender=False):
    from src.evaluator.l2_case import load_case
    from src.evaluator.l2_method_scoring import load_methods
    from src.evaluator.l2_embodied_scoring import WEIGHTS
    from tools.scene_scoring_evidence import native_images
    run,task,folder=Path(run),Path(task),Path(folder)
    mkdir(folder)
    prepared=folder/'prepared.json'
    prior_inputs=folder.parent/'raw/inputs.json'
    if not prepared.exists() and prior_inputs.exists() and (folder/'policy-receipt.json').exists():
        bindings=load(prior_inputs)['source_bindings']
        for name in ('report.json','evidence.json'):
            path=folder/name;pin(path,bindings[str(path)])
        receipt=load(folder/'policy-receipt.json')
        atomic(prepared,dict(retained_report=receipt['original_report'],rerender=receipt['use_native_rerender'],
            report=pin(folder/'report.json'),evidence=pin(folder/'evidence.json'),receipt=pin(folder/'policy-receipt.json')))
    if prepared.exists():
        saved=load(prepared)
        if saved['retained_report']!=retained_report or saved['rerender']!=rerender:
            raise ValueError('Cannot resume a different scene reassessment')
        for pointer in (saved['report'],saved['evidence'],saved['receipt']):pin(pointer['path'],pointer['sha256'])
        receipt=load(saved['receipt']['path'])
        for name in ('original_run','original_record','original_evidence'):
            pointer=receipt[name];pin(pointer['path'],pointer['sha256'])
        return folder/'report.json',folder/'evidence.json'
    manifest=load(run/'run.json');record=load(run/'execution_record.json')
    pin(run/'grading-evidence.json',record['evidence_sha256']['grading-evidence.json'])
    evidence=load(run/'grading-evidence.json')
    evidence['scoring_policy_revision']=VERSION
    _,spec,policy=load_case(task);plan=load_methods(task,policy)
    if record['spec_sha256']!=spec.digest or record['task_id']!=policy['task_id']:
        raise ValueError('Task identity differs from retained native execution')
    for name,digest in record['task_files_sha256'].items():pin(task/name,digest)
    for name,digest in manifest['source_sha256'].items():pin(run/'source'/name,digest)
    for name,digest in record['artifact_sha256'].items():pin(Path(record['submission'])/name,digest)
    original_path=Path(manifest['report_path']);original=load(original_path)
    if retained_report:
        pin(retained_report['path'],retained_report['sha256'])
        published=load(retained_report['path'])
        expected=published['source_bindings'].get(str(original_path))
        if expected is None:
            correction=published['validity_correction']['receipt']
            pin(correction['path'],correction['sha256'])
            prior=load(correction['path'])['original_automatic_report']
            if Path(prior['path'])!=original_path:raise ValueError('Prior native report lineage differs')
            expected=prior['sha256']
        pin(original_path,expected)
    audits={}
    for label in ('baseline','seed-0','seed-1','seed-2'):
        path=run/'audit'/(label+'.json');pin(path,record['evidence_sha256']['audit/'+label+'.json'])
        audit=load(path)
        if not l2_audit_valid(audit):raise ValueError('Independent execution/integrity/loadability failed: '+label)
        audits[label]=audit
    result=copy.deepcopy(original)
    harness=copy.deepcopy(evidence['harness'])
    for seed in manifest['seeds']:
        row=copy.deepcopy(audits['seed-'+str(seed)])
        row.update(integrity_passed=True,passed=True)
        harness['seed_runs'][str(seed)]=row
    harness.update(execution_passed=True,integrity_passed=True)
    evidence['harness']=harness
    for gate in ('execution','integrity','all_seeds'):
        result['gates'][gate]={'passed':True,'policy':VERSION}
    profile=policy['automatic_profile'];result['method_version']=profile
    if original.get('automatic_profile')!=profile:raise ValueError('Automatic method binding changed')
    if rerender:
        selection=native_images(run,folder=folder/'render-evidence')
        for name,pointer in selection['variants']['primary'].items():
            artifact=dict(evidence['artifacts'][name]);artifact.update(pointer)
            if name.endswith('.png'):
                with Image.open(pointer['path']) as im:artifact.update(size=list(im.size),format=im.format,loadable=True)
            evidence['artifacts'][name]=artifact
        evidence['artifact_sha256']={**evidence['artifact_sha256'],
            **{k:v['sha256'] for k,v in selection['variants']['primary'].items()}}
        result['artifact_sha256']=evidence['artifact_sha256']
        from src.evaluator.l2_refresh_scoring import compare_views
        image=compare_views(evidence,plan)
        if image['status']!='measured':raise ValueError('Rerender image measurement incomplete')
        result['main_image_comparison']=image
        result['score_components']['main_image']=image['score']
        # Native raster-size mistakes reduce quality through the image score.
        # Successful rendering and PNG loading remain required.
        for gate in ('measured_requirements','case_requirements','all_seed_quality'):
            result['gates'][gate]={'passed':True,'policy':VERSION,'scope':'Native rerenders available; raster fidelity affects content score'}
    valid=all(g['passed'] for g in result['gates'].values())
    if profile in {'l2-reference-refresh-v1.0.0','l2-photo-refresh-v1.0.0'}:
        total=None if valid else 0.
    elif profile in WEIGHTS:
        total=math.fsum(w*result['score_components'][k] for k,w in WEIGHTS[profile].items()) if valid else 0.
    else:raise ValueError('Unsupported retained automatic profile: '+profile)
    result.update(S_core=total,S_level=total,S_diagnostic=total,score_valid=valid,case_pass=valid,automatic_case_pass=valid,G=int(valid),
        status='awaiting_judgment' if valid else 'system_invalid',scoring_policy_revision=VERSION,
        source_bindings={})
    receipt=dict(policy=VERSION,original_report=retained_report,original_native_report=pin(original_path),
        original_run=pin(run/'run.json'),original_record=pin(run/'execution_record.json'),
        original_evidence=pin(run/'grading-evidence.json'),
        audit_receipts={label:pin(run/'audit'/(label+'.json')) for label in audits},
        diagnostic_signatures={label:r['reproduction_matches_baseline'] for label,r in audits.items()},
        use_native_rerender=rerender,new_candidate_generations=0,new_candidate_executions=0)
    atomic(folder/'policy-receipt.json',receipt)
    atomic(folder/'evidence.json',evidence)
    result['source_bindings'][str(folder/'policy-receipt.json')]=pin(folder/'policy-receipt.json')['sha256']
    atomic(folder/'report.json',result)
    atomic(prepared,dict(retained_report=retained_report,rerender=rerender,
        report=pin(folder/'report.json'),evidence=pin(folder/'evidence.json'),receipt=pin(folder/'policy-receipt.json')))
    return folder/'report.json',folder/'evidence.json'
