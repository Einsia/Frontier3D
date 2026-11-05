"""Rebuild a frozen project in Docker and collect L3 geometry/reference evidence.

No model credentials, other submissions or host repository are mounted. The
caller must supply an engine copy dedicated to this submission.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import make_plans,reference_plan,read_json,write_json,tree_digest,DOORS,CHESTS,digest
from harness.L3.MinecraftVillage.scene_geometry import Scene,static_measure,motion_measure
from harness.L3.MinecraftVillage.evaluate import local_diagnostics
from harness.L3.MinecraftVillage.inventory import local as inventory_local
from harness.L3.MinecraftVillage.calibration import ground_plan,apply_ground_observations
from harness.L3.Suite.replay_budget import retry_budget
from tools.capture_l3_algorithms import replay_timeout


def start_verifier_container(command, output):
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode(errors='replace') if isinstance(value,bytes) else value or ''
        (output/'container-start.log').write_text(text(error.stdout)+text(error.stderr)+'\nDocker startup timed out after 180 seconds; container state requires reconciliation.\n')
        raise RuntimeError('Verifier container startup timed out after 180 seconds') from error
    (output/'container-start.log').write_text(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('Verifier container startup failed: '+result.stderr.strip())
    return result

def stop_verifier_container(name, output):
    try:
        result=subprocess.run(['docker','stop','--time','10',name],capture_output=True,text=True,timeout=30)
        record={'container':name,'return_code':result.returncode,'stderr':result.stderr}
    except subprocess.TimeoutExpired:
        record={'container':name,'timed_out':True,'timeout_seconds':30}
    write_json(output/'container-stop.json',record)


def prepare_verifier_project(source, project, observer):
    shutil.copytree(source,project,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache'))
    plugin=project/'Plugins/BenchRuntime'
    if plugin.exists():shutil.rmtree(plugin)
    shutil.copytree(observer,plugin)
    descriptor=next(project.glob('*.uproject'));desc=read_json(descriptor)
    names={'BenchRuntime','PythonScriptPlugin','EditorScriptingUtilities'}
    desc['Plugins']=[p for p in desc.get('Plugins',[]) if p['Name'] not in names]+[{'Name':n,'Enabled':True} for n in sorted(names)]
    write_json(descriptor,desc)
    return descriptor

def validate_early_startup(source, project, observer, previous, output):
    if previous.get('verification_source_sha256') or previous.get('episodes'):
        raise ValueError('Early startup recovery cannot replace frozen measurement evidence')
    proof=output/'failed-attempts'/('startup-proof-'+str(time.time_ns()))
    proof.mkdir(parents=True)
    prepare_verifier_project(source,proof/'project',observer)
    expected=tree_digest(proof/'project');actual=tree_digest(project)
    write_json(proof/'validation.json',{'expected_sha256':expected,'actual_sha256':actual,'matches':expected==actual})
    if actual!=expected:raise ValueError('Pristine verifier project changed before startup')
    # ue.py requires a fresh output directory; preserve failed build evidence
    # only after the original submission and trusted verifier both validate.
    build=project.parent/'build'
    if build.is_symlink():raise ValueError('Build output symlink forbidden')
    if build.exists():
        if not build.is_dir():raise ValueError('Build output is not a directory')
        archived=proof/'build-output'
        hashes={str(p.relative_to(build)):digest(p) for p in build.rglob('*') if p.is_file()}
        build.rename(archived)
        write_json(proof/'build-output.json',{'original':str(build),'archived':str(archived),'files_sha256':hashes})
    return expected


def seed_trusted_cache(source, manifest, destination):
    """Only organizer caches frozen before generation may seed a fresh verifier."""
    info=read_json(manifest)
    if info.get('provenance')!='organizer_preflight' or info.get('captured_before_candidate_generation') is not True:
        raise ValueError('Cache is not an organizer preflight snapshot')
    files=info['files']
    for relative,expected in files.items():
        rel=Path(relative)
        if rel.is_absolute() or '..' in rel.parts:raise ValueError('Cache path escapes snapshot')
        path=source/rel
        if any(p.is_symlink() for p in [path,*path.parents]) or not path.is_file() or digest(path)!=expected:
            raise ValueError('Cache snapshot integrity failed: '+relative)
    if set(files)!={str(p.relative_to(source)) for p in source.rglob('*') if p.is_file()}:
        raise ValueError('Unlisted files in cache snapshot')
    for relative in files:
        out=destination/relative;out.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/relative,out)
    return {'manifest_sha256':digest(manifest),'file_count':len(files),'provenance':info['provenance']}


def diagnose_local(folder,plan,binding):
    # Missing/duplicate public IDs are candidate contract failures. Preserve
    # strict measurement failures for malformed or incomplete observer evidence.
    frame=read_json(folder/'before.json')
    if frame.get('protocol')!='ue5-observer-v1':raise ValueError('Unknown observation protocol')
    matches=[e for e in frame['entities'] if e.get('id')==plan['target']]
    if len(matches)!=1:
        return {'target':plan['target'],'status':'submission_contract_failure',
                'error':'Target must occur exactly once','observed_target_count':len(matches),
                'automatic_fraction':None,'checks':{},
                'not_measured':'Interaction semantics require a unique runtime entity with the declared public ID.'}
    return local_diagnostics(folder,plan,binding)



def prepare_episode_replay(workspace, output, key, plan):
    """Archive incomplete evidence and budget a retry without changing its plan."""
    episodes=workspace/'episodes'
    folder=episodes/key
    log=output/('episode_'+key+'.log')
    if folder.exists():
        if read_json(folder/'plan.json')!=plan:
            raise ValueError('Incomplete episode plan changed: '+key)
        stamp=str(time.time_ns())
        folder.rename(episodes/(key+'-failed-'+stamp))
        if log.exists():
            archive=output/'failed-attempts';archive.mkdir(exist_ok=True)
            shutil.copy2(log,archive/(stamp+'-'+log.name))
    return retry_budget(plan,episodes,key,log)

def calibration_retry_allowed(previous, workspace):
    """Retry only failed pre-episode calibration; never replace measured episodes."""
    if previous.get('status') != 'failed' or not str(previous.get('error', '')).startswith('ground_calibration '):
        return False
    if previous.get('episodes') or list((workspace/'episodes').glob('*/completed.json')):
        return False
    if (workspace/'ground_calibration/completed.json').exists():
        return False
    return bool(previous.get('verification_source_sha256'))


def verify(source,output,engine,gpu,fixture=False,cache=None,annotations=None,trial=None,trusted_cache=None,trusted_cache_manifest=None,resume=False,collect_only=False):
    repo=Path(__file__).resolve().parents[1]
    original_digest=tree_digest(source)  # Reject symlinks before copying candidate files.
    if cache and not fixture:raise ValueError('Cache override is restricted to the known integration fixture')
    if engine==(Path(os.environ.get('L3_UE_ROOT',str(repo.parent/'engines/UE_5.8.3_source/UnrealEngine-release')))).resolve():
        raise ValueError('Verification requires a dedicated engine copy')
    previous=None;early_startup=False;calibration_retry=False
    if resume:
        previous=read_json(output/'run.json')
        workspace=output/'workspace';project=workspace/'project';public=output/'public'
        plugin=project/'Plugins/BenchRuntime';descriptor=next(project.glob('*.uproject'))
        if previous.get('status')!='failed':raise ValueError('Only failed verification may be resumed')
        if previous.get('source_sha256')!=original_digest:raise ValueError('Original submission changed')
        if previous.get('verification_source_sha256'):
            if previous['verification_source_sha256']!=tree_digest(project):raise ValueError('Frozen verifier project changed')
        else:
            validate_early_startup(source,project,repo/'ue5/BenchRuntime',previous,output)
            early_startup=True
        if previous.get('observer_sha256')!=tree_digest(plugin):raise ValueError('Observer changed')
        if tree_digest(repo/'ue5/BenchRuntime')!=tree_digest(plugin):raise ValueError('Observer version changed')
        if digest(public/'ue.py')!=digest(repo/'ue5/agent_environment/ue.py'):raise ValueError('Render helper changed')
        if not early_startup and not (workspace/'ground_calibration/completed.json').exists():
            calibration_retry=calibration_retry_allowed(previous,workspace)
            if not calibration_retry:raise ValueError('Resume requires completed ground calibration')
        cache_record=previous.get('trusted_cache')
        archive=output/'failed-attempts';archive.mkdir(exist_ok=True)
        write_json(archive/(str(time.time_ns())+'-run.json'),previous)
        shutil.copy2(output/'container-start.log',archive/(str(time.time_ns())+'-container-start.log'))
    else:
        output.mkdir(parents=True,exist_ok=False);workspace=output/'workspace';workspace.mkdir()
        project=workspace/'project'
        descriptor=prepare_verifier_project(source,project,repo/'ue5/BenchRuntime')
        public=output/'public';public.mkdir()
        shutil.copy2(repo/'ue5/agent_environment/ue.py',public/'ue.py')
        shutil.copy2(repo/'tools/ue_create_l3_mask_material.py',public/'ue_create_l3_mask_material.py')
        plugin=project/'Plugins/BenchRuntime'
        (workspace/'.home').mkdir();(workspace/'.cache/ue').mkdir(parents=True)
        cache_record=None
        if not cache and trusted_cache is None and trusted_cache_manifest is None:
            from tools.l3_eval_cache import configured_cache
            configured=configured_cache()
            if configured:trusted_cache,trusted_cache_manifest=configured
        if bool(trusted_cache)!=bool(trusted_cache_manifest):raise ValueError('Both trusted cache and manifest are required')
        if cache and trusted_cache:raise ValueError('Choose one cache source')
        if trusted_cache:cache_record=seed_trusted_cache(trusted_cache,trusted_cache_manifest,workspace/'.cache/ue')
    base=Path(os.environ.get('L3_UE_ROOT',str(repo.parent/'engines/UE_5.8.3_source/UnrealEngine-release')))
    name='l3-verify-'+output.name.lower().replace('_','-')[:40]+'-'+hashlib.sha256(str(output).encode()).hexdigest()[:10]
    image=os.environ.get('L3_UE_IMAGE','sha256:0f9fa1e7b6845a07df402171ce77517943b65945bd12935d99a58e9a24d84dd4')
    cmd=['docker','run','-d','--name',name,'--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
         '--cpus','16','--memory','64g','--pids-limit','4096','--shm-size','2g','--gpus','device='+str(gpu),
         '--user',f'{os.getuid()}:{os.getgid()}','-e','HOME=/workspace/.home','-e','UE5_ROOT='+str(base),
         '-e','NVIDIA_DRIVER_CAPABILITIES=graphics,utility,compute','-e','UE_LocalDataCachePath=/workspace/.cache/ue']
    for host,dest,ro in [(workspace,'/workspace',False),(public,'/opt/l3-public',True),(engine,str(base),False)]:
        cmd+=['--mount',f'type=bind,src={host},dst={dest}'+(',readonly' if ro else '')]
    from tools.l3_content_protection import content_mounts
    cmd += content_mounts(output,project,original_digest)
    if cache:
        # The caller may only use this for the exact same candidate's shader cache.
        cmd+=['--mount',f'type=bind,src={cache},dst=/workspace/.cache/ue']
    cmd+=[image]
    if previous and previous.get('command')!=cmd:raise ValueError('Verifier container configuration changed')
    record={'kind':'integration_fixture_regression' if fixture else 'submission_verification','formal_score':None,
            'integration_fixture':fixture,'source_sha256':original_digest,'source':str(source),
            'observer_sha256':tree_digest(plugin),'trusted_cache':cache_record,'container':name,'command':cmd,'status':'starting','episodes':{}}
    if previous:
        if not early_startup:record['verification_source_sha256']=previous['verification_source_sha256']
        record['early_startup_recovery']=early_startup
        record['calibration_retry']=calibration_retry
        record['resume_of_failed_run']=True
        record['episodes']=previous.get('episodes',{})
        record['resumed_evidence_sha256']={str(p.relative_to(output)):digest(p) for p in (workspace/'episodes').rglob('*') if p.is_file() and p.suffix in {'.json','.png'}}
    write_json(output/'run.json',record)
    def execute(label,args,timeout=1800):
        record['status']=label;write_json(output/'run.json',record)
        with (output/(label+'.log')).open('w') as log:
            try:p=subprocess.run(['docker','exec',name,*args],stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            except subprocess.TimeoutExpired:raise RuntimeError(label+' timed out')
        from tools.l3_content_protection import audit_content
        content_audit=audit_content(output,project,original_digest,label)
        if content_audit:record['runtime_content']=content_audit;write_json(output/'run.json',record)
        if p.returncode:raise RuntimeError(label+' exited '+str(p.returncode))
    started=False
    try:
        start_verifier_container(['docker','start',name] if resume else cmd,output)
        started=True
        if not resume or early_startup:
            execute('build',['python3','/opt/l3-public/ue.py','build','/workspace/project','--output','/workspace/build','--jobs','16','--blueprints'],3600)
            execute('mask_material',[str(base/'Engine/Binaries/Linux/UnrealEditor-Cmd'),'/workspace/project/'+descriptor.name,
                    '-run=pythonscript','-script=/opt/l3-public/ue_create_l3_mask_material.py','-unattended','-NullRHI','-nosplash','-nosound','-nop4','-DDC=NoZenLocalFallback'])
            if not (project/'Content/L3Verifier/M_InstanceMask.uasset').exists():raise RuntimeError('Trusted mask material missing')
        frozen=tree_digest(project);record['verification_source_sha256']=frozen
        bindings=read_json(project/'bindings.json')
        calibration=ground_plan(bindings)
        if calibration_retry:
            if read_json(workspace/'plans/ground_calibration.json')!=calibration:
                raise ValueError('Calibration retry plan changed')
            failed=workspace/'ground_calibration'
            if failed.exists():failed.rename(workspace/('ground_calibration-failed-'+str(time.time_ns())))
            oldlog=output/'ground_calibration.log'
            if oldlog.exists():shutil.copy2(oldlog,output/'failed-attempts'/(str(time.time_ns())+'-ground_calibration.log'))
        write_json(workspace/'plans/ground_calibration.json',calibration)
        if not resume or early_startup or calibration_retry:
            execute('ground_calibration',['python3','/opt/l3-public/ue.py','preview','/workspace/project','--output',
                    '/workspace/ground_calibration','--plan','/workspace/plans/ground_calibration.json','--timeout',str(replay_timeout(calibration))],replay_timeout(calibration)+300)
        observations={s['name']:read_json(workspace/'ground_calibration'/(s['name']+'_event.json')) for s in calibration['steps']}
        bindings,ground=apply_ground_observations(bindings,observations)
        write_json(output/'ground-calibration.json',ground);write_json(output/'calibrated-bindings.json',bindings)
        failures={}
        plans=make_plans(bindings,failures=failures);plans['reference']=reference_plan(bindings)
        from harness.L3.MinecraftVillage.resource_chain import plan as resource_plan, diagnose as resource_diagnose
        try:plans['resource_chain']=resource_plan(bindings)
        except (KeyError,TypeError,ValueError) as error:
            failures['resource_chain']={'status':'submission_contract_failure','error':str(error),'measured':False}
        record['submission_contract_failures']=failures
        write_json(output/'submission-contract.json',{'failures':failures,'passed':not failures,'formal_score':None})
        for key,plan in plans.items():
            pp=workspace/'plans'/(key+'.json')
            if record['episodes'].get(key,{}).get('completed'):
                if read_json(pp)!=plan:raise ValueError('Completed episode plan changed: '+key)
                if not read_json(workspace/'episodes'/key/'completed.json').get('completed'):raise ValueError('Completed evidence missing: '+key)
            else:
                budget,budget_evidence=prepare_episode_replay(workspace,output,key,plan)
                record.setdefault('episode_budgets',{})[key]={'timeout_seconds':budget,'evidence':budget_evidence}
                write_json(pp,plan)
                execute('episode_'+key,['python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/episodes/'+key,
                        '--plan','/workspace/plans/'+pp.name,'--timeout',str(budget)],budget+300)
                record['episodes'][key]={'completed':True}
            if key=='resource_chain':
                record['episodes'][key]['diagnostics']=resource_diagnose(workspace/'episodes'/key)
                write_json(output/'resource-chain.json',record['episodes'][key]['diagnostics'])
            elif plan['kind']=='local':
                record['episodes'][key]['diagnostics']=diagnose_local(workspace/'episodes'/key,plan,bindings['entities'][plan['target']])
                record['episodes'][key]['inventory']=inventory_local(workspace/'episodes'/key,plan['target'],required=not fixture)
            write_json(output/'run.json',record)
        if tree_digest(project)!=frozen:raise RuntimeError('Submission source/assets changed during evaluation')
        geometry=workspace/'episodes/views/scene_geometry.json'
        if not collect_only:
            from harness.L3.MinecraftVillage.physical_scene import physical_scene
            physical,background_audit=physical_scene(read_json(geometry),trial)
            write_json(output/'physical-scene.json',physical)
            write_json(output/'background-exclusions.json',background_audit)
            scene=Scene(physical)
            measures={'geometry_sha256':digest(geometry),'static':static_measure(scene),'motion':motion_measure(scene,workspace/'episodes')}
            from harness.L3.MinecraftVillage.support import measure as support_measure
            measures['support']=support_measure(physical)
            write_json(output/'geometry.json',measures)
        if trial is not None:
            from harness.L3.MinecraftVillage.asset_usage import audit as audit_assets
            equipment=read_json(trial/'preflight-complete.json');manifest=trial/'workspace/kenney-import.json'
            if digest(manifest)!=equipment['input_and_material_hashes']['kenney-import.json']:
                raise RuntimeError('Organizer material manifest differs from frozen equipment')
            write_json(output/'asset-usage.json',audit_assets(read_json(geometry),read_json(manifest),
                project,equipment['input_and_material_hashes']))
        ref=workspace/'episodes/reference';mask_event=read_json(ref/'reference_ids_event.json')
        render_log=(ref/'editor.log').read_text(errors='replace')
        if 'missing usage flag' in render_log or 'Failed to compile Material' in render_log:
            raise RuntimeError('Reference mask/material renderer used a fallback shader')
        if not mask_event.get('accepted'):raise RuntimeError('Mask renderer failed')
        pose=read_json(ref/'reference_pose.json')['camera'];mask_pose=read_json(ref/'mask_pose.json')['camera']
        if pose!=mask_pose:raise RuntimeError('RGB and mask cameras differ')
        rgb_sha=digest(ref/'reference_rgb.png')
        write_json(output/'reference-view.json',{'protocol':'joint_scene_camera_prediction','evaluator_rendered':True,
            'candidate_sha256':rgb_sha,'reference_sha256':digest(repo/'tasks/L3/MinecraftVillage/environment/input/reference.jpg'),
            'camera':pose,'posthoc_alignment':False})
        groups=next(s['groups'] for s in plans['reference']['steps'] if s['op']=='instance_masks')
        write_json(output/'mask-palette.json',{'groups':groups,'camera':pose,'color_encoding':'ue_srgb_linear_display_gamma_2_2','candidate_sha256':rgb_sha,
            'mask_sha256':digest(ref/'reference_mask.png'),'nonopaque_components':mask_event.get('nonopaque_components',[])})
        if annotations is not None:
            from harness.L3.MinecraftVillage.reference import evaluate as evaluate_reference
            shutil.copy2(annotations,output/'reference-annotations.json')
            write_json(output/'reference.json',evaluate_reference(repo/'tasks/L3/MinecraftVillage/environment/input/reference.jpg',
                ref/'reference_rgb.png',output/'reference-annotations.json',output/'reference-view.json',
                ref/'reference_mask.png',output/'mask-palette.json'))
        record['status']='collected' if collect_only else 'measured'
        if not collect_only:record['geometry_sha256']=digest(output/'geometry.json')
        else:record['geometry_status']='separate_algorithm_worker'
        record['evidence_sha256']={str(p.relative_to(output)):digest(p) for p in (workspace/'episodes').rglob('*') if p.is_file() and p.suffix in {'.json','.png'}}
        write_json(output/'run.json',record)
    except Exception as error:
        record.update(status='failed',error=str(error));write_json(output/'run.json',record);raise
    finally:
        if started:stop_verifier_container(name,output)
    print(json.dumps({'status':record['status'],'episodes':len(record['episodes']),'formal_score':None}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['project','output','engine-copy']:p.add_argument('--'+arg,type=Path,required=True)
    p.add_argument('--trusted-cache',type=Path);p.add_argument('--trusted-cache-manifest',type=Path);p.add_argument('--trial',type=Path);p.add_argument('--annotations',type=Path);p.add_argument('--gpu',type=int,required=True);p.add_argument('--integration-fixture',action='store_true');p.add_argument('--cache',type=Path)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--collect-only',action='store_true',help='Collect immutable engine evidence; measure geometry separately')
    a=p.parse_args();verify(a.project.resolve(),a.output.resolve(),a.engine_copy.resolve(),a.gpu,a.integration_fixture,a.cache.resolve() if a.cache else None,a.annotations.resolve() if a.annotations else None,a.trial.resolve() if a.trial else None,a.trusted_cache.resolve() if a.trusted_cache else None,a.trusted_cache_manifest.resolve() if a.trusted_cache_manifest else None,a.resume,a.collect_only)
