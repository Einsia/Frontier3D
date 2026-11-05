"""Judge an existing L2 run with frozen VLM rules; archive a new blended report."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import argparse

from pathlib import Path

import time

from harness.L2.vlm_judge import JudgeConfig, judge_task,verify_packet

from src.agent_judge.protocol import read_json,write_json,digest,score

from src.agent_judge.generated import verified_evidence

from src.evaluator.l2_case import load_case

from src.evaluator.l2_method_scoring import load_methods

from src.evaluator.l2_requirements import digest as object_digest

from src.evaluator.l2_vlm_scoring import add_vlm

def replay_judgment(path,plan,evidence,model):
    path=Path(path).resolve();run=read_json(path/'run.json');packet=path/'packet';manifest=read_json(packet/'manifest.json')
    if (digest(packet/'manifest.json')!=run['packet_sha256'] or digest(path/'issues.json')!=run['response_sha256']
            or digest(packet/'judge_spec.json')!=plan['_vlm_judge']['spec_sha256']
            or run.get('tested_model')!=model
            or manifest['mode']!=plan['_vlm_judge']['mode'] or run.get('mode')!=manifest['mode']):
        raise ValueError('VLM replay identity/spec/response mismatch')
    verify_packet(packet,manifest)
    from src.agent_judge import l2_fidelity
    if plan['_vlm_judge']['spec']['protocol']==l2_fidelity.PROTOCOL:
        l2_fidelity.verify_packet_inputs(plan['_vlm_judge']['spec'],manifest)
    for name in ['main.png','alternate.png']+(['novel.png'] if 'novel.png' in evidence.get('artifacts',{}) else []):
        if manifest['sha256'].get('candidate/'+name)!=evidence['artifacts'][name]['sha256']:
            raise ValueError('VLM replay candidate image mismatch')
    if plan['_vlm_judge']['spec']['family'] != 'Brief2Scene':
        expected_references = {
            f'reference/reference-{index}{Path(item["path"]).suffix.lower()}': item['sha256']
            for index, (_, item) in enumerate(sorted(evidence.get('reference_images', {}).items()))
        }
        actual_references = {name: value for name, value in manifest['sha256'].items()
                             if name.startswith('reference/reference-')}
        if not expected_references or expected_references != actual_references:
            raise ValueError('VLM replay reference image mismatch')
    if plan['_vlm_judge'].get('edit_context'):
        for role,item in plan['_vlm_judge']['edit_context'].items():
            if manifest['sha256'].get('reference/'+role+'.png')!=item['sha256']:
                raise ValueError('VLM replay before/target image mismatch')
    if manifest['mode'] == 'interactive':
        if manifest['sha256'].get('candidate/scene.blend') != evidence['artifacts']['scene.blend']['sha256']:
            raise ValueError('VLM replay native scene mismatch')
    for name,expected in run['source_bindings'].items():
        if digest(Path(name))!=expected:raise ValueError('VLM replay source changed')
    directory=path/f"attempt-{run['accepted_attempt']}"
    paths=verified_evidence(manifest,directory/'generated' if manifest['mode']=='interactive' else None)
    result=score(read_json(path/'issues.json'),plan['_vlm_judge']['spec'],paths)
    if result.get('localization'):
        result['localization']['image_sha256']=evidence['artifacts']['main.png']['sha256']
    return {**run,**result,'replayed_from':str(path),'new_judge_calls':0}

def generation_provenance(source_run, generation_source_run=None, task=None):
    source_run = Path(source_run).resolve()
    origin = Path(generation_source_run).resolve() if generation_source_run else source_run
    bindings = {}
    if origin != source_run:
        replay, original = read_json(source_run/'run.json'), read_json(origin/'run.json')
        same_spec = replay.get('spec_sha256') == original.get('spec_sha256')
        if not same_spec and task is not None:
            # Early unified generation receipts recorded raw file bytes while
            # native L2 runs record EvalSpec's canonical JSON digest. Prove
            # both against the same validated task; never rewrite the receipt.
            task = Path(task)
            _, spec, policy = load_case(task)
            spec_path, instruction = task/'harness/eval_spec.json', task/'instruction.md'
            same_spec = (original.get('spec_sha256') == digest(spec_path)
                         and replay.get('spec_sha256') == spec.digest
                         and original.get('instruction_sha256') == digest(instruction)
                         and original.get('task_id') == policy['task_id'])
            if same_spec:
                bindings[str(spec_path.resolve())] = digest(spec_path)
                bindings[str(instruction.resolve())] = digest(instruction)
        if (replay.get('model_call') is not False or not (original.get('model_call') is True or original.get('provided_source') is True)
                or not original.get('source_sha256')
                or replay.get('source_sha256') != original['source_sha256']
                or replay.get('task_id') != original.get('task_id')
                or not same_spec):
            raise ValueError('Reexecution does not preserve original model code and task')
        for folder in (source_run, origin):
            bindings[str(folder/'run.json')] = digest(folder/'run.json')
            for name, expected in original['source_sha256'].items():
                path = folder/'source'/name
                if digest(path) != expected:
                    raise ValueError('Reexecution source file changed: '+name)
                bindings[str(path)] = expected
    generation = origin/'generation.json'
    if not generation.exists():
        if origin != source_run:
            raise ValueError('Original model generation evidence missing')
        return None, bindings
    bindings[str(generation)] = digest(generation)
    model = next((r.get('model') for r in reversed(read_json(generation).get('attempts',[])) if r.get('model')), None)
    if origin != source_run and model is None and not read_json(origin/'run.json').get('provided_source'):
        raise ValueError('Original model identity missing')
    return model, bindings

def rescore(task,source_run,output,*,env_file=None,config=None,blender=None,report_path=None,evidence_path=None,timeout=1800,judge_run=None,generation_source_run=None):
    task,source_run,output=Path(task).resolve(),Path(source_run).resolve(),Path(output).resolve()
    if output.is_relative_to(source_run) or source_run.is_relative_to(output):
        raise ValueError('New review must be separate from the source run')
    _,spec,policy=load_case(task);plan=load_methods(task,policy)
    report_path=Path(report_path or source_run/'evaluation/report.json').resolve()
    evidence_path=Path(evidence_path or source_run/'grading-evidence.json').resolve()
    base,evidence=read_json(report_path),read_json(evidence_path)
    # Generation-first runs retain the automatic total inside the deferred
    # VLM envelope. Recover that recorded total, never infer it from a score.
    if base.get('method_version')==policy['scoring_profile'] and base.get('automatic_profile')==policy['automatic_profile']:
        if 'automatic_score' not in base:raise ValueError('Deferred report lacks its original automatic total')
        base={**base,'method_version':policy['automatic_profile'],'S_core':base['automatic_score']}
    if base['task_id']!=policy['task_id'] or base['spec_sha256']!=spec.digest or base['method_version']!=policy['automatic_profile']:
        raise ValueError('Original report must match the task and automatic profile')
    artifact_hashes=base.get('artifact_sha256',{})
    bindings={str(p):digest(p) for p in [report_path,evidence_path,task/'harness/case.json',task/'harness/methods.json',task/plan['vlm_judge']['spec_path']]}
    for name,item in evidence.get('artifacts',{}).items():
        if name in {'main.png','alternate.png','scene.blend'}:
            if artifact_hashes.get(name)!=item.get('sha256') or digest(Path(item['path']))!=item['sha256']:
                raise ValueError('Historical report/image/native binding mismatch')
            bindings[str(Path(item['path']).resolve())]=item['sha256']
    # References must belong to the newly frozen task, not arbitrary historical paths.
    evidence['reference_images']={view:{'path':str(task/name),'sha256':digest(task/name)} for view,name in spec.reference_images.items()}
    bindings.update({item['path']:item['sha256'] for item in evidence['reference_images'].values()})
    model, generation_bindings = generation_provenance(source_run, generation_source_run, task)
    bindings.update(generation_bindings)
    output.mkdir(parents=True,exist_ok=True)
    if (output/'inputs.json').exists() and read_json(output/'inputs.json')['source_bindings']!=bindings:
        raise ValueError('Cannot resume changed retrospective inputs')
    if (output/'result.json').exists():
        previous=read_json(output/'result.json')
        if digest(output/'report.json')!=previous['report_sha256']:raise ValueError('Completed rescore changed')
        return read_json(output/'report.json')
    write_json(output/'inputs.json',{'source_bindings':bindings,'source_run':str(source_run),
        'tested_model':model,'new_candidate_generations':0,'new_candidate_executions':0})
    if base.get('score_valid') is True:
        judgment=replay_judgment(judge_run,plan,evidence,model) if judge_run else judge_task(task,evidence,plan,output/'judge',config=config,env_file=env_file,
            tested_model=model,blender=blender,deadline=time.monotonic()+timeout)
    else:
        judgment={'status':'not_measurable','S_vlm':None,'reason':'Automatic system validity not established; judge skipped'}
    report=add_vlm(base,judgment,policy['scoring_profile'])
    report.update(case_policy_sha256=object_digest(policy),evaluation_kind='retrospective_vlm_pilot',
        execution_proof_valid=False,validity_source='Inherited from hash-bound automatic report; no new execution capability',
        source_bindings=bindings,source_report_path=str(report_path),source_report_sha256=digest(report_path),
        new_candidate_generations=0,new_candidate_executions=0,report_path=str(output/'report.json'))
    for name,expected in bindings.items():
        if digest(Path(name))!=expected:raise ValueError('Source changed during VLM review')
    write_json(output/'report.json',report)
    write_json(output/'result.json',{'task_id':policy['task_id'],'model':model,'profile':policy['scoring_profile'],
        'status':report['status'],'old_score':base.get('S_core'),'score':report['S_core'],
        'vlm':report['S_vlm'],'judge_model':judgment.get('model'),
        'report_path':str(output/'report.json'),'report_sha256':digest(output/'report.json')})
    return report
