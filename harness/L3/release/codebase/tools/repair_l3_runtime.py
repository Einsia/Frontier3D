"""Replay interaction evidence with geometry-derived poses, preserving originals."""
import argparse,json,subprocess,time,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,tree_digest,digest,local_plan,REQUIRED,BLOCKS
from harness.L3.MinecraftVillage.geometry_routes import derive_bindings,retarget_removed_block
from harness.L3.MinecraftVillage.algorithm_workflow import door_walk_plan,diagnose_doors,make_workflow,diagnose
from harness.L3.MinecraftVillage.resource_chain import plan as resource_plan,diagnose as resource_diagnose
from harness.L3.MinecraftVillage.inventory import local as inventory_local
from harness.L3.MinecraftVillage.scene_geometry import Scene,motion_measure
from tools.verify_l3_submission import diagnose_local
from tools.capture_l3_algorithms import replay_timeout


def load_geometry(trial, geometry=None):
    path=geometry if geometry is not None else trial/'evaluation-algorithm-v1/geometry/physical-scene.json'
    return path,read_json(path)


def episode_hashes(folder):
    return {str(p.relative_to(folder)):digest(p) for p in folder.rglob('*') if p.is_file() and p.suffix in {'.json','.png'}}

def reusable_episode(sub,key,plan,record):
    folder=sub/key;planfile=sub/(key+'-plan.json')
    if not record.get('completed') or not planfile.exists() or not (folder/'completed.json').exists():return False
    if read_json(planfile)!=plan or not read_json(folder/'completed.json').get('completed'):return False
    hashes=episode_hashes(folder)
    if record.get('evidence_sha256') and record['evidence_sha256']!=hashes:
        raise ValueError('Runtime episode evidence changed: '+key)
    record['evidence_sha256']=hashes
    return True

def repair(trial,run,output,geometry=None,resume=False):
    from tools.l3_ground_query import prepare_ground_observer
    pawn_ground=prepare_ground_observer(run,output)
    started=time.monotonic();r=read_json(run/'run.json');source=tree_digest(trial/'workspace/project')
    if source!=r['source_sha256']:raise ValueError('Frozen candidate changed')
    before=tree_digest(run/'workspace/project')
    if before!=r['verification_source_sha256']:raise ValueError('Verifier source changed')
    geometry_path,ex=load_geometry(trial,geometry)
    prior=read_json(output/'run.json') if resume and (output/'run.json').exists() else None
    if prior and (prior['source_sha256']!=source or prior['verification_source_sha256']!=before or prior['geometry_sha256']!=digest(geometry_path)):
        raise ValueError('Runtime resume source/geometry mismatch')
    output.mkdir(exist_ok=bool(prior));sub=run/'workspace/runtime-geometry-v2';sub.mkdir(exist_ok=bool(prior))
    if prior:shutil.copy2(output/'run.json',output/('run-attempt-'+str(time.time_ns())+'.json'))
    state=prior or {'status':'planning','source_sha256':source,'verification_source_sha256':before,'episodes':{},'started_at_unix':time.time(),'geometry_path':str(geometry_path),'geometry_sha256':digest(geometry_path)}
    state.pop('error',None)
    def save():write_json(output/'run.json',state)
    save()
    try:
        bindings,audit=derive_bindings(ex,read_json(run/'calibrated-bindings.json'),read_json(run/'workspace/episodes/views/initial.json'))
        write_json(output/'pose-audit.json',audit)
    except Exception as error:
        state.update(status='failed',error=str(error),phase='planning');save();raise
    engines=[x.split('src=',1)[1].split(',dst=',1)[0] for x in r['command'] if x.startswith('type=bind,src=') and '/engines/' in x]
    from tools.prepare_l3_trial import assert_engine_available
    for engine_source in engines:assert_engine_available(Path(engine_source).resolve())
    container=r['container']
    def execute(key,plan):
        record=state['episodes'].get(key,{})
        if reusable_episode(sub,key,plan,record):
            state['episodes'][key]=record;save();return sub/key
        from harness.L3.Suite.replay_budget import retry_budget
        timeout,budget_evidence=retry_budget(plan,sub,key,output/(key+'.log'),replay_folders=[sub/key,*sub.glob(key+'-failed-*')])
        stamp=str(time.time_ns())
        for entry in budget_evidence:
            if entry['archive']==str(sub/key):entry['archive']=str(sub/(key+'-failed-'+stamp))
        for partial in [sub/key,output/(key+'.log'),sub/(key+'-plan.json')]:
            if partial.exists():partial.rename(partial.with_name(partial.name+'-failed-'+stamp))
        write_json(sub/(key+'-plan.json'),plan);state['status']='episode_'+key;save();t=time.monotonic()
        write_json(output/(key+'-walltime-budget.json'),{'timeout_seconds':timeout,'evidence':budget_evidence})
        cmd=['docker','exec',container,'python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/runtime-geometry-v2/'+key,'--plan','/workspace/runtime-geometry-v2/'+key+'-plan.json','--timeout',str(timeout)]
        with (output/(key+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=f,timeout=timeout+120).returncode
        folder=sub/key
        if rc or not read_json(folder/'completed.json').get('completed'):raise RuntimeError('Capture failed '+key+' rc='+str(rc))
        state['episodes'][key]={'completed':True,'seconds':time.monotonic()-t,'evidence_sha256':episode_hashes(folder)};save();return folder
    try:
        subprocess.run(['docker','start',container],check=True,stdout=subprocess.DEVNULL,timeout=180)
        steps=[];keys=[]
        for target,b in bindings['entities'].items():
            for field in ['approach_cm','crossing_from_cm','crossing_to_cm']:
                if field not in b:continue
                p=b[field];name=target.replace('.','_')+'_'+field;keys.append((target,field,name))
                steps.append({'op':'ray',**({'collision_channel':'pawn'} if pawn_ground else {}),'name':name,'from_cm':[p[0],p[1],p[2]+100],'to_cm':[p[0],p[1],p[2]-300]})
        folder=execute('pose_ground',{'version':1,'kind':'views','steps':steps});ground={}
        from harness.L3.MinecraftVillage.ground_perimeter import ground_hit,perimeter_probes,choose_ground
        events={name:read_json(folder/(name+'_event.json')) for _,_,name in keys}
        unresolved=[(target,field,name) for target,field,name in keys
                    if not ground_hit(events[name],pawn_ground)]
        fallback={}
        if unresolved and pawn_ground:
            probes,options=perimeter_probes(ex,bindings,unresolved)
            if probes:
                fallback_folder=execute('pose_ground_fallback',{'version':1,'kind':'views','steps':probes})
                fallback_events={s['name']:read_json(fallback_folder/(s['name']+'_event.json')) for s in probes}
                for name,choices in options.items():
                    selected=choose_ground(choices,fallback_events)
                    if selected:fallback[name]=selected
                write_json(output/'ground-fallback-audit.json',{'method':'geometry_perimeter_verified_pawn_ground_v1',
                    'unresolved':unresolved,'options':options,'selected':fallback,
                    'scoring':'Pose selection only; all movement, ray/range and interaction outcomes require subsequent real episodes.'})
        for target,field,name in keys:
            event=events[name]
            if ground_hit(event,pawn_ground):
                bindings['entities'][target][field][2]=event['point_cm'][2]+88
                ground[name]=event
            elif name in fallback:
                bindings['entities'][target][field]=fallback[name]['position_cm']
                ground[name]=fallback[name]['event']
            else:raise ValueError('Ground ray unresolved '+name)
        write_json(output/'ground.json',ground);write_json(output/'bindings.json',bindings)
        # Execute the entire uninterrupted task before isolated fixture tests.
        p,m=make_workflow(ex,bindings,read_json(run/'workspace/episodes/views/initial.json'))
        write_json(output/'workflow-meta.json',m);folder=execute('workflow',p)
        write_json(output/'workflow.json',diagnose(folder,m))
        p,m=door_walk_plan(bindings);write_json(output/'door-meta.json',m);folder=execute('door_walk',p)
        write_json(output/'door-walk.json',diagnose_doors(folder,m))
        for target in REQUIRED:
            p=local_plan(target,bindings['entities'][target]);key=target.replace('.','_');folder=execute(key,p)
            if target in BLOCKS:
                revised,audit=retarget_removed_block(p,read_json(folder/'after_1.json'),target)
                audit.update(snapshot=str(folder/'after_1.json'),snapshot_sha256=digest(folder/'after_1.json'))
                write_json(output/(key+'-retarget.json'),audit)
                if audit['retargeted']:
                    p=revised;folder=execute(key+'_retargeted',p)
                    state['episodes'][key]['evaluation_episode']=key+'_retargeted'
            state['episodes'][key]['diagnostics']=diagnose_local(folder,p,bindings['entities'][target])
            state['episodes'][key]['inventory']=inventory_local(folder,target,required=True);save()
        folder=execute('resource_chain',resource_plan(bindings));write_json(output/'resource-chain.json',resource_diagnose(folder))
        state['status']='motion';save();write_json(output/'motion.json',motion_measure(Scene(ex),sub))
        if tree_digest(trial/'workspace/project')!=source or tree_digest(run/'workspace/project')!=before:raise ValueError('Source changed')
        state.update(status='measured',elapsed_seconds=time.monotonic()-started,
            evidence_sha256={str(p.relative_to(run)):digest(p) for p in sub.rglob('*') if p.is_file() and p.suffix in {'.json','.png'}},
            diagnostics_sha256={p.name:digest(p) for p in output.glob('*.json') if p.name!='run.json'})
        save()
    except Exception as error:state.update(status='failed',error=str(error));save();raise
    finally:subprocess.run(['docker','stop','--time','10',container],capture_output=True,timeout=30)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ['trial','run','output']:p.add_argument('--'+k,type=Path,required=True)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--geometry',type=Path,help='Physical scene produced by this evaluation run')
    a=p.parse_args();repair(a.trial.resolve(),a.run.resolve(),a.output.resolve(),a.geometry.resolve() if a.geometry else None,resume=a.resume)
