"""Run equipment checks before a timed autonomous trial, preserving every result."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.asset_usage import audit as audit_assets
from tools.l3_usage import summarize_requests
from tools.l3_generation_retry import run_generation
from tools.l3_api_control import stopped,is_transient,BalanceExhausted


def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def run(root, generate=False, equipment_only=False):
    environment=json.loads((root/'environment.json').read_text())
    container=environment['container'];workspace=root/'workspace'
    images=environment.get('reference_images',['/workspace/input/reference.jpg'])
    image_args=[arg for path in images for arg in ['--image',path]]
    record={'status':'preflight_running','benchmark_score':None,'checks':{}}
    if (root/'trial.json').exists():
        number=1
        while (root/f'trial-attempt-{number:03}.json').exists():number+=1
        (root/f'trial-attempt-{number:03}.json').write_bytes((root/'trial.json').read_bytes())
    def save(): (root/'trial.json').write_text(json.dumps(record,indent=2)+'\n')
    def command(name,args,timeout=1800,stdin=None):
        logpath=root/(name+'.log');number=2
        while logpath.exists():logpath=root/(name+f'-{number:03}.log');number+=1
        with logpath.open('w') as log:
            try:
                result=subprocess.run(['docker','exec','-i',container,*args],input=stdin,
                                      stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
                record['checks'][name]={'passed':result.returncode==0,'return_code':result.returncode,'log':logpath.name}
            except subprocess.TimeoutExpired:
                # docker exec client termination alone does not stop UE children.
                subprocess.run(['docker','stop','--time','10',container],capture_output=True)
                record['checks'][name]={'passed':False,'timed_out':True}
        save()
        if not record['checks'][name]['passed']:raise RuntimeError(name+' failed; see preserved log')
    try:
        save()
        if not (root/'preflight-complete.json').exists():
            if (root/'preparation.json').exists():
                prep=json.loads((root/'preparation.json').read_text());pid=prep['engine_copy_pid']
                while Path(f'/proc/{pid}/cmdline').exists() and Path(f'/proc/{pid}/cmdline').read_bytes().startswith(b'cp\0'):
                    time.sleep(10)
                if (root/'engine-copy.log').read_text().strip():raise RuntimeError('Engine copy produced errors')
            build_folder='preflight-build';number=2
            while (workspace/'checks'/build_folder).exists():build_folder=f'preflight-build-{number:03}';number+=1
            command('build-preflight',['python3','/opt/l3-public/ue.py','build','/workspace/project','--output','/workspace/checks/'+build_folder,'--jobs','16'],3600)
            engine=next(x.split('=',1)[1] for x in environment['docker_command'] if x.startswith('UE5_ROOT='))
            if (root/'paired-inputs.json').exists():
                from tools.l3_paired_inputs import validate as validate_pair
                pair=validate_pair(root)
                record['checks']['material-import']={'passed':True,'mode':'hash_verified_baseline_assets',
                                                     'baseline_preflight_sha256':pair['baseline_preflight_sha256']}
                save()
            else:
                command('material-import',[engine+'/Engine/Binaries/Linux/UnrealEditor-Cmd','/workspace/project/L3Environment.uproject',
                        '-run=pythonscript','-script=/opt/l3-public/ue_import_l3_kenney.py','-unattended','-NullRHI','-nosplash','-nosound','-nop4','-DDC=NoZenLocalFallback'],1800)
            imported=json.loads((workspace/'kenney-import.json').read_text())
            if len(imported['assets'])!=85:raise RuntimeError('The complete voxel pack was not imported')
            preview_folder='preflight-preview';number=2
            while (workspace/'checks'/preview_folder).exists():preview_folder=f'preflight-preview-{number:03}';number+=1
            plan={'version':1,'kind':'development_preview','steps':[
                {'op':'camera','position_cm':[650,-850,650],'target_cm':[160,80,50]},
                {'op':'wait','seconds':2}, {'op':'export_geometry','name':'material_geometry'},
                {'op':'capture','name':'preview'},
                {'op':'camera','position_cm':[160,500,160],'target_cm':[160,850,100]},
                {'op':'wait','seconds':2},{'op':'capture','name':'interior'}]}
            (workspace/'preflight-plan.json').write_text(json.dumps(plan))
            command('material-preview',['python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/checks/'+preview_folder,
                                       '--plan','/workspace/preflight-plan.json'],1800)
            frozen={str(p.relative_to(workspace)):sha(p) for p in workspace.rglob('*') if p.is_file() and
                    (str(p.relative_to(workspace)).startswith('input/') or p.name in {'PROMPT.md','kenney-import.json'} or
                     any(str(p.relative_to(workspace)).startswith(x) for x in ['project/Content/','project/Source/','project/Plugins/','project/Config/']) and not set(p.relative_to(workspace).parts)&{'Binaries','Intermediate'} or p.suffix=='.uproject')}
            public={str(p.relative_to(root/'public')):sha(p) for p in (root/'public').rglob('*') if p.is_file()}
            (root/'preflight-complete.json').write_text(json.dumps({'checks':record['checks'],'input_and_material_hashes':frozen,
                    'public_tool_hashes':public,'asset_count':85,'preview':'workspace/checks/'+preview_folder+'/preview.png',
                    'geometry':'workspace/checks/'+preview_folder+'/material_geometry.json'},indent=2)+'\n')
        frozen_record=json.loads((root/'preflight-complete.json').read_text())
        record['checks'].update(frozen_record['checks'])
        for relative,expected in frozen_record['input_and_material_hashes'].items():
            if sha(workspace/relative)!=expected:raise RuntimeError('Preflight input changed: '+relative)
        for relative,expected in frozen_record.get('public_tool_hashes',{}).items():
            if sha(root/'public'/relative)!=expected:raise RuntimeError('Preflight tool changed: '+relative)
        imported=json.loads((workspace/'kenney-import.json').read_text())
        geometry=json.loads((root/frozen_record['geometry']).read_text())
        usage=audit_assets(geometry,imported,workspace/'project',frozen_record['input_and_material_hashes'])
        (root/'preflight-asset-usage.json').write_text(json.dumps(usage,indent=2)+'\n')
        if usage.get('used_materials')!=6 or usage.get('unresolved_material_references'):
            raise RuntimeError('Material preview did not substantiate the six supplied sample materials')
        if any(not valid for row in usage['materials'] for valid in row['texture_bytes_match_preloaded_assets'].values()):
            raise RuntimeError('Preloaded material texture bytes changed')
        from tools.l3_equipment_check import inspect_equipment
        preview_path=root/frozen_record['preview']
        visual=inspect_equipment(preview_path,preview_path.with_name('interior.png'))
        (root/'preflight-image-check.json').write_text(json.dumps(visual,indent=2)+'\n')
        record['checks']['image_preflight']=visual
        if not visual['passed']:raise RuntimeError('Equipment sky/interior image checks failed; see preflight-image-check.json')
        record['equipment_status']='ready';save()
        if equipment_only:
            record['status']='equipment_ready_model_not_probed';save();return
        (root/'model-stage.txt').write_text('preflight_probe')
        probe=(workspace/'PROMPT.md').read_text()+"\n\nCONNECTION CHECK ONLY: Inspect the supplied task inputs and briefly describe the intended scene and confirm you can work with this task. Do not call tools, edit files or begin authoring."
        probe_attempt=0
        while True:
            if stopped():raise BalanceExhausted('API balance exhausted before generation')
            probe_attempt+=1
            try:
                command('model-gateway-probe',['codex','exec','--ephemeral','--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check',
                    '--json','--model',environment['model'],*image_args,'--output-last-message','/workspace/model-gateway-ready.txt','-'],None,probe.encode())
                break
            except RuntimeError:
                if stopped():raise BalanceExhausted('API balance exhausted during connection probe')
                log=root/record['checks']['model-gateway-probe']['log']
                if not is_transient(log.read_text(errors='replace')):raise
                record.update(status='retrying_model_connection',probe_attempts=probe_attempt);save()
                time.sleep(min(15*probe_attempt,120))
        if not (workspace/'model-gateway-ready.txt').read_text().strip():raise RuntimeError('Empty model probe output')
        from tools.l3_trial_status import has_authoring_activity
        if has_authoring_activity(root/record['checks']['model-gateway-probe']['log']):raise RuntimeError('Connection probe unexpectedly used authoring tools')
        for relative,expected in frozen_record['input_and_material_hashes'].items():
            if sha(workspace/relative)!=expected:raise RuntimeError('Input changed during model probe: '+relative)
        (root/'probe-usage.json').write_text(json.dumps(summarize_requests(root/'model-requests.jsonl','preflight_probe'),indent=2)+'\n')
        record['status']='ready';save()
        if not generate:return
        commandline=['docker','exec','-i',container,'codex','exec','--dangerously-bypass-approvals-and-sandbox','--skip-git-repo-check',
                     '--json','--model',environment['model'],*image_args,'--output-last-message','/workspace/agent-final.txt','-']
        (root/'model-stage.txt').write_text('generation')
        record.update(status='generating',started_unix=time.time(),budget_seconds=environment['budget_seconds'],model=environment['model']);save()
        from tools.l3_delivery import delivery_feedback as check_delivery
        initial_project={k.removeprefix('project/'):v for k,v in frozen_record['input_and_material_hashes'].items() if k.startswith('project/')}
        def delivery_feedback(timing):
            return check_delivery(workspace,timing,initial_project=initial_project)
        timing=run_generation(commandline,(workspace/'PROMPT.md').read_bytes(),root,environment['budget_seconds'],completion_feedback=delivery_feedback if environment.get('completion_policy')=='complete_delivery' else None)
        for key in ['generation_status','return_code','elapsed_seconds','model_error_events']:record[key]=timing[key]
        record['finished_unix']=time.time()
        stop=subprocess.run(['docker','stop','--time','10',container],capture_output=True,text=True)
        (root/'generation-container-stop.log').write_text(stop.stdout+stop.stderr)
        if stop.returncode:
            record.update(status='generation_cleanup_failed',error='Cannot confirm generation container stopped; submission is not frozen')
            save();return
        (root/'generation-usage.json').write_text(json.dumps(summarize_requests(root/'model-requests.jsonl'),indent=2)+'\n')
        (root/'model-stage.txt').write_text('post_generation')
        files={str(p.relative_to(workspace/'project')):sha(p) for p in (workspace/'project').rglob('*') if p.is_file() and
               not set(p.relative_to(workspace/'project').parts)&{'Binaries','Intermediate','Saved','DerivedDataCache'}}
        (root/'submission-manifest.json').write_text(json.dumps(files,indent=2)+'\n')
        from tools.l3_trial_status import has_authoring_activity
        record['authoring_activity_observed']=has_authoring_activity(root/'agent-events.jsonl')
        initial_project={k.removeprefix('project/'):v for k,v in frozen_record['input_and_material_hashes'].items() if k.startswith('project/')}
        def scene_file(name):return name.startswith(('Source/','Content/','Config/')) or name.endswith('.uproject')
        record['scene_files_changed']=sorted(k for k in set(files)|set(initial_project)
                                             if scene_file(k) and files.get(k)!=initial_project.get(k))
        from tools.l3_trial_status import completion_evidence
        record['completion_evidence']=completion_evidence(workspace,timing)
        record['status']=('generation_failed_before_authoring' if not record['scene_files_changed']
                          else 'generated_awaiting_independent_verification' if record['completion_evidence']['delivery_complete']
                          else 'generation_incomplete_candidate_frozen')
        if timing['generation_status']=='api_balance_exhausted':record['status']='stopped_api_balance_exhausted'
        if not record['scene_files_changed']:record['error']='No scene source, configuration or content differs from the equipment fixture'
        record['submission_manifest_sha256']=sha(root/'submission-manifest.json');save()
    except Exception as error:
        record.update(status='stopped_api_balance_exhausted' if isinstance(error,BalanceExhausted) else 'blocked_preflight' if 'generation_status' not in record else 'verification_required',error=str(error));save()
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);g=p.add_mutually_exclusive_group();g.add_argument('--generate',action='store_true');g.add_argument('--equipment-only',action='store_true');a=p.parse_args();run(a.output.resolve(),a.generate,a.equipment_only)
