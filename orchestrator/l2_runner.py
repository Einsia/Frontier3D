"""L2 case generation/execution, fresh seeds, read-only audits and task-owned grading."""
from __future__ import annotations
from harness.common.experiment_policy import (GENERATION_TIMEOUT, GENERATION_TOTAL_TIMEOUT, EXECUTION_TIMEOUT, EVALUATION_TIMEOUT)

import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from datetime import datetime, timezone

from harness.L2.audit import artifact_state
from src.evaluator.l2 import score_l2
from src.evaluator.l2_case_audit import audit_case
from src.evaluator.l2_case_compare import align_evaluated_roundoff
from src.evaluator.l2_case import load_case, CASE_VERSION
from src.evaluator.l2_quality_scoring import QUALITY_PROFILES, EDIT_TARGET_PROFILE
from src.evaluator.l2_requirements import digest
from .feedback import DEFAULT_ATTEMPTS, retry_policy
from .generator import generate
from .l2_inspection import inspect_scene, reproduce, reproduce_flexible, InvalidGeometryError
from .l2_record import issue_context
from .runner import snapshot, execute, unchanged, generation_validator
from .runtime import seconds
from .tasks import PROJECT, TASKS, load_task, sha256, regular, write_json


def case_evidence(facts, artifacts, policy, baseline=None, cameras=None):
    scene = dict(facts.get('scene',{}))
    scene['cameras'] = dict(scene.get('cameras',{}))
    for artifact, view in (cameras or {}).items():
        if view['camera'] in scene['cameras']:
            scene['cameras']['__'+Path(artifact).stem] = scene['cameras'][view['camera']]
    evidence = {'geometry_root':facts.get('geometry_root'),'scene':scene,'artifacts':artifacts,'baseline':(baseline or {}).get('scene',{})}
    if baseline:
        evidence['baseline'] = dict(baseline['scene'])
        evidence['baseline']['cameras'] = dict(baseline['scene']['cameras'])
        active = baseline['scene'].get('active_camera')
        if active:
            evidence['baseline']['cameras']['__main'] = baseline['scene']['cameras'][active]
    return evidence


def implementation_hashes():
    return {str(p.relative_to(PROJECT)):sha256(p) for folder,pattern in (
        ('orchestrator','*.py'),('src','run_usage.py'),('src/evaluator','l2*.py'),('src/evaluator','spec.py'),
        ('src/evaluator','metrics.py'),('harness/L2','audit.py'),('harness/L2','vlm_judge.py'),
        ('src/agent_judge','*.py')) for p in sorted((PROJECT/folder).glob(pattern))}


def run_case(task_id, *, submission=None, generate_code=False, tasks_root=TASKS,
             output_root=PROJECT/'data/task_runs',blender=None,runtime='docker',
             image='3dbench-l1-blender:mvp',timeout=None,attempt_timeout=EXECUTION_TIMEOUT,attempts=DEFAULT_ATTEMPTS,
             reproduction=True,generator_runtime='docker',generator_image=None,
             generation_timeout=GENERATION_TIMEOUT,reproduction_timeout=EXECUTION_TIMEOUT,generation_total_timeout=GENERATION_TOTAL_TIMEOUT,env_file=None):
    timeout = timeout if timeout is not None else EVALUATION_TIMEOUT + (generation_total_timeout if generate_code else 0)
    started = time.monotonic()
    deadline = started+seconds(timeout)
    seconds(attempt_timeout);seconds(reproduction_timeout)
    retry_config = retry_policy(attempts)
    if (submission is None) == (not generate_code):
        raise ValueError('Choose exactly one source: --submission or --generate')
    task = load_task(task_id,tasks_root)
    _,spec,policy = load_case(task.root)
    from src.evaluator.l2_embodied_scoring import base_policy
    effective_policy=base_policy(policy)
    content_quality = effective_policy.get('scoring_profile') in QUALITY_PROFILES
    blender = Path(blender or PROJECT/'third_party/blender-5.2.1-linux-x64/blender').resolve(strict=True)
    output_root = Path(output_root).resolve();output_root.mkdir(parents=True,exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix=task.root.name+'-',dir=output_root))
    manifest = {'protocol':CASE_VERSION,'task_id':task.id,'run_dir':str(run),'status':'running','phase':'prepare',
        'started_utc':datetime.now(timezone.utc).isoformat(),'runtime':runtime,'image':image,
        'model_call':generate_code,'tokens':None,'spec_sha256':spec.digest,'case_policy_sha256':digest(policy),
        'implementation_sha256':implementation_hashes(),'attempts':{},'seeds':list(spec.seeds),
        'retry_policy':retry_config,
        'resource_limits':{'source_bytes':128*1024**2,'output_bytes':2*1024**3,'memory':'8g','cpus':min(8,len(os.sched_getaffinity(0)))},
        'isolation_scope':'Docker candidate network disabled; inputs read-only; private task solution never mounted'
            if runtime=='docker' else 'Trusted local code only; no candidate isolation'}
    if policy.get('scoring_profile'):
        manifest.update(method_version=policy['scoring_profile'],methods_sha256=policy['methods_sha256'],
            formal_score_eligible=False)
    write_json(run/'run.json',manifest)
    print('Run archive: '+str(run),flush=True)
    def remaining(limit):
        value = min(limit,max(0,deadline-time.monotonic()))
        if value <= 0:raise TimeoutError('L2 total budget exhausted')
        return value
    try:
        task_files = [task.manifest['instruction'],'task.toml','harness/case.json','harness/eval_spec.json','harness/evaluate.py']
        if policy.get('scoring_profile'):
            task_files += ['harness/methods.json','solution/EVALUATION.md']
            from src.evaluator.l2_method_scoring import load_methods
            preliminary=load_methods(task.root,policy)
            if preliminary.get('reference_annotation'):
                task_files.append(preliminary['reference_annotation']['path'])
            if preliminary.get('reference_boxes'):
                task_files.append(preliminary['reference_boxes']['path'])
            if preliminary.get('vlm_judge'):
                task_files.append(preliminary['vlm_judge']['spec_path'])
            if preliminary.get('reference_target'):
                task_files += list(preliminary['reference_target']['files'])
            if preliminary.get('edit_initial_image'):
                task_files.append(preliminary['edit_initial_image'])
        task_files += [task.manifest['environment']+'/'+p for p in task.manifest['environment_files']]
        task_hashes = {p:sha256(regular(task.root,p)) for p in task_files}
        write_json(run/'configuration/task.json',task.manifest)
        write_json(run/'configuration/eval_spec.json',spec.to_dict())
        write_json(run/'configuration/case.json',policy)
        methods=None
        if policy.get('scoring_profile'):
            from src.evaluator.l2_method_scoring import load_methods
            methods=load_methods(task.root,policy)
            write_json(run/'configuration/methods.json',methods)
        baseline = None
        reference_target = None
        if spec.baseline_scene:
            manifest['phase']='inspect-initial';write_json(run/'run.json',manifest)
            baseline = inspect_scene(task.root/spec.baseline_scene,run/'initial-inspection',blender,
                runtime=runtime,image=image,deadline=deadline,timeout=remaining(reproduction_timeout))
        if methods and methods.get('reference_target'):
            target=methods['reference_target']
            reference_target=inspect_scene(task.root/target['scene'],run/'target-reference-inspection',blender,
                runtime=runtime,image=image,deadline=deadline,timeout=remaining(reproduction_timeout))
        if generate_code:
            manifest['phase']='generation';write_json(run/'run.json',manifest)
            submission,history = generate(task,run,deadline=min(deadline,time.monotonic()+seconds(generation_total_timeout)),timeout=remaining(generation_timeout),
                attempts=attempts,env_file=env_file,runtime=generator_runtime,image=generator_image,
                validate_submission=generation_validator(task,run,manifest,blender=blender,
                    runtime=runtime,image=image,seed=spec.seeds[0],attempt_timeout=attempt_timeout))
            manifest['generation_attempts']=history
            deadline = min(deadline,time.monotonic()+EVALUATION_TIMEOUT)
            timeout = min(timeout,EVALUATION_TIMEOUT)
            manifest['evaluation_deadline_monotonic'] = deadline
        source = run/'source'
        source_hashes = snapshot(Path(submission).resolve(),source,exclude=('scene.blend','scene.glb','main.png','alternate.png','novel.png'))
        regular(source,'solution.py');regular(source,'README.md')
        manifest['source_sha256']=source_hashes
        seed_results, canonical, evidence = {}, None, {}
        baseline_result = None
        reference_images = {view:{'path':str(task.root/name),'sha256':sha256(task.root/name)} for view,name in spec.reference_images.items()}
        original = None
        original_scene = None
        original_geometry_root = None
        for label,seed in [('baseline',spec.seeds[0]),*((f'seed-{s}',s) for s in spec.seeds)]:
            manifest['phase']=label;write_json(run/'run.json',manifest)
            if generate_code and label=='baseline':
                history=manifest['attempts']['baseline']
                if history[-1]['source_sha256']!=source_hashes:
                    raise ValueError('Accepted source differs from validated source')
            else:
                history = execute(task,source,source_hashes,run/label,blender=blender,runtime=runtime,
                    image=image,seed=seed,attempts=attempts,deadline=deadline,attempt_timeout=attempt_timeout)
            manifest['attempts'][label]=history
            row = {'execution_passed':bool(history and history[-1]['status']=='success'),
                'integrity_passed':False,'quality_passed':False,'quality_evaluated':False,'passed':False}
            output = Path(history[-1]['workspace'])/'output' if history else None
            observed = None
            if output and row['execution_passed']:
                try:
                    facts = inspect_scene(output/'scene.blend',run/(label+'-inspection'),blender,
                        runtime=runtime,image=image,deadline=deadline,timeout=remaining(reproduction_timeout))
                    audit = audit_case(facts,baseline,policy)
                    row['audit']=audit
                    replay = {'passed':False,'status':'not_configured'}
                    if reproduction and audit['passed']:
                        from src.evaluator.l2_method_scoring import REFERENCE_SCENE_PROFILES, REFRESH_PROFILES
                        refresh=effective_policy.get('scoring_profile') in REFRESH_PROFILES
                        render_verifier=reproduce_flexible if content_quality or refresh or effective_policy.get('scoring_profile') in REFERENCE_SCENE_PROFILES else reproduce
                        replay = render_verifier(output,facts,run/(label+'-rerender'),blender,
                            runtime=runtime,image=image,deadline=deadline,timeout=remaining(reproduction_timeout),
                            baseline=baseline,**({'artifacts':tuple(n for n in spec.required_artifacts if n.endswith('.png'))} if refresh else {}))
                    row['rerender']=replay
                    artifacts,errors = artifact_state(output,spec.required_artifacts,())
                    artifacts = {name:{**v,'loadable':True,'path':str(output/name)} for name,v in artifacts.items()}
                    from PIL import Image
                    for name in ('main.png','alternate.png','novel.png'):
                        if name in artifacts:
                            with Image.open(output/name) as im:artifacts[name].update(size=list(im.size),format=im.format)
                    observed = case_evidence(facts,artifacts,policy,baseline,replay.get('views'))
                    observed['reference_images']=reference_images
                    if methods and methods.get('edit_initial_image'):
                        initial_image=task.root/methods['edit_initial_image']
                        observed['edit_initial_image']={'path':str(initial_image),'sha256':sha256(initial_image)}
                    if reference_target and methods.get('edit_measurement_mode') != 'lighting':
                        from src.evaluator.l2_edit_target import compare_visible_target
                        observed['edit_target']=compare_visible_target(facts,baseline,reference_target,methods['reference_target']['objects'])
                        if methods.get('edit_structure'):
                            from src.evaluator.l2_edit_structure import measure_structure
                            observed['edit_structure']=measure_structure(facts,baseline,reference_target,
                                methods['reference_target']['objects'],methods['edit_structure'])
                        if methods.get('edit_regions'):
                            from src.evaluator.l2_edit_regions import required_regions
                            observed['edit_regions']=required_regions(facts,baseline,reference_target,methods['edit_regions'])
                        if methods.get('edit_components'):
                            from src.evaluator.l2_cylindrical_components import cylindrical_containers
                            observed['edit_components']=cylindrical_containers(facts,baseline,reference_target,
                                methods['reference_target']['objects'],methods['edit_components'])
                    observed['case']={'edit_target_added':bool(audit.get('target_geometry_additions')),
                        'preservation':audit.get('content_passed',audit['passed']),
                        'preservation_details':audit.get('content_failures',[])}
                    if effective_policy.get('scoring_profile') == EDIT_TARGET_PROFILE:
                        from src.evaluator.l2_edit_target_scoring import measure_edit_target
                        observed['native_edit_target'] = measure_edit_target(
                            facts,baseline,reference_target,methods,policy,audit,observed)
                    comparable,roundoff = align_evaluated_roundoff(facts['scene'],original_scene or facts['scene'],directory=facts.get('geometry_root'),reference_directory=original_geometry_root or facts.get('geometry_root'))
                    row['reproducibility_roundoff']=roundoff
                    signature = {n:{k:o.get(k) for k in ('type','parent','visible_render','location','rotation','scale','geometry_sha256','evaluated_geometry_sha256','material_sha256','data_sha256','constraints_sha256')}
                                 for n,o in comparable['objects'].items()}
                    from src.evaluator.l2_mesh_order import reproduction_fields
                    for name,obj in comparable['objects'].items():
                        signature[name].update(reproduction_fields(obj))
                    row['face_order_normalized_objects']=[n for n,o in comparable['objects'].items()
                        if o.get('native_order_independent_sha256') and o.get('surface_order_independent_sha256')]
                    signature={'objects':signature, **{k:facts['scene'].get(k) for k in ('world_sha256','render_settings_sha256','saved_frame','unit_scale','cameras','audit')}}
                    row['reproducibility_sha256']=digest(signature)
                    if label=='baseline':
                        original=row['reproducibility_sha256'];original_scene=facts['scene'];original_geometry_root=facts.get('geometry_root')
                    row['reproduction_matches_baseline']=original==row['reproducibility_sha256']
                    from src.evaluator.content_evidence_policy import rerender_available
                    row['integrity_passed']=audit['passed'] and (replay['passed'] or rerender_available(replay)) and not errors
                    row['passed']=row['execution_passed'] and row['integrity_passed']
                    row['reproduction_signature_affects_eligibility']=False
                    if methods:
                        from src.evaluator.l2_method_scoring import score_measured
                        quality=score_measured(spec,observed,policy,methods,execution_required=False)
                    else:
                        quality=score_l2(spec,observed)
                    row.update(quality_evaluated=True,quality_passed=quality['task_quality_pass'])
                    if content_quality:
                        row.update(quality_meaning='system_validity_only',
                            content_score=quality['S_level'],content_requirements=quality['content_requirements'])
                except (OSError,ValueError,RuntimeError) as error:
                    row.update(error=str(error)[:2048])
                    if isinstance(error,RuntimeError) and str(error).startswith(('L2 inspection timeout:',
                            'L2 inspection infrastructure_error:','L2 inspection cleanup_failed:')):
                        row['measurement_status']='not_measurable'
            if label=='baseline':
                baseline_result = row
                if output is None:
                    output=run/'empty-output';output.mkdir()
                canonical=run/'submission';snapshot(output,canonical,max_bytes=2*1024**3)
                evidence=observed or {'scene':{},'artifacts':{},'reference_images':reference_images}
            else:
                seed_results[str(seed)]=row
            write_json(run/'audit'/f'{label}.json',row)
        manifest['phase']='scoring';write_json(run/'run.json',manifest)
        artifact_hashes={n:sha256(regular(canonical,n)) for n in task.artifacts if (canonical/n).is_file()}
        for name,item in evidence.get('artifacts',{}).items():item['path']=str(canonical/name)
        evidence['artifact_sha256']=artifact_hashes
        evidence['case'] = {'edit_target_added': bool(baseline_result.get('audit',{}).get('target_geometry_additions')),
            'preservation':baseline_result.get('audit',{}).get('content_passed',baseline_result.get('audit',{}).get('passed',False)),
            'preservation_details':baseline_result.get('audit',{}).get('content_failures',[])}
        evidence['harness']={'execution_passed':baseline_result['execution_passed'] and all(v['execution_passed'] for v in seed_results.values()),
            'integrity_passed':baseline_result['integrity_passed'] and all(v['integrity_passed'] for v in seed_results.values()) and unchanged(source,source_hashes),
            'seed_runs':seed_results}
        evidence['harness']['measurement_failures']=[{'phase':label,'error':row['error']}
            for label,row in [('baseline',baseline_result),*((f'seed-{s}',r) for s,r in seed_results.items())]
            if row.get('measurement_status')=='not_measurable']
        if manifest['implementation_sha256'] != implementation_hashes():
            evidence['harness']['measurement_failures'].append({
                'phase':'implementation', 'error':'Evaluator implementation changed during execution; reassessment required'})
        if methods and methods.get('_reference_boxes') and (canonical/'main.png').is_file():
            from .l2_detection import detect_reference_objects
            manifest['phase']='object-detection';write_json(run/'run.json',manifest)
            # Run once on the canonical main image; seed validity was independently
            # checked above. Detector faults never trigger a new model generation.
            evidence['object_detection']=detect_reference_objects(canonical/'main.png',
                methods['_reference_boxes'],run/'object-detection',timeout=max(1.,min(300.,deadline-time.monotonic())))
        if methods and methods.get('_vlm_judge'):
            from harness.L2.vlm_judge import judge_task
            if (evidence['harness']['execution_passed'] and evidence['harness']['integrity_passed']
                    and not evidence['harness']['measurement_failures']):
                manifest['phase']='vlm-judging';write_json(run/'run.json',manifest)
                generation_file=run/'generation.json'
                generation_info=json.loads(generation_file.read_text()) if generation_file.exists() else {}
                tested=next((r.get('model') for r in reversed(generation_info.get('attempts',[])) if r.get('model')),None)
                evidence['vlm_judgment']=judge_task(task.root,evidence,methods,run/'vlm-judge',
                    env_file=env_file,tested_model=tested,blender=blender,deadline=deadline)
            else:
                evidence['vlm_judgment']={'status':'not_measurable','S_vlm':None,
                    'reason':'VLM skipped: automatic system validity not established'}
        write_json(run/'grading-evidence.json',evidence)
        hashes={str(p.relative_to(run)):sha256(p) for p in run.rglob('*') if p.is_file() and p.name!='run.json'}
        record={'protocol':CASE_VERSION,'task_id':task.id,'trial_id':run.name,'spec_sha256':spec.digest,
            'case_policy_sha256':digest(policy),'task_files_sha256':task_hashes,'submission':str(canonical),
            'artifact_sha256':artifact_hashes,'evidence_path':'grading-evidence.json','evidence_sha256':hashes}
        write_json(run/'execution_record.json',record)
        context=issue_context(run/'execution_record.json',trial_id=run.name,model_call=generate_code)
        entry=importlib.util.spec_from_file_location('l2_case_entry',task.root/'harness/evaluate.py')
        module=importlib.util.module_from_spec(entry);entry.loader.exec_module(module)
        report=module.evaluate(canonical,blender,execution_context=context,output=run/'evaluation')
        from src.evaluator.l2_case_diagnostics import prepare_case_review
        prepare_case_review(evidence,report,policy,run/'review')
        manifest['review_packet']=str(run/'review/packet.json')
        manifest.update(status='scored' if time.monotonic()<deadline else 'budget_exhausted',phase='finished',report_path=report['report_path'],evidence_path=report['evidence_path'],
            case_pass=report['case_pass'],S_core=report['S_core'],S_diagnostic=report['S_diagnostic'])
        if methods and methods.get('_vlm_judge') and report['S_core'] is None:
            manifest.update(status='not_measurable',measurement_reason='VLM or automatic quality evidence incomplete; inspect report')
    except BaseException as error:
        manifest.update(status='invalid_task_input' if isinstance(error,InvalidGeometryError) and manifest['phase']=='inspect-initial' else 'interrupted' if isinstance(error,(KeyboardInterrupt,SystemExit)) else 'failed',
            error_type=type(error).__name__,error=str(error)[:2048])
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
    finally:
        manifest['elapsed_seconds']=time.monotonic()-started
        manifest['implementation_unchanged']=manifest['implementation_sha256']==implementation_hashes()
        write_json(run/'run.json',manifest)
    return manifest
