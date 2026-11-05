"""Supplement frozen independent verification with camera and walking evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest,tree_digest
from harness.L3.MinecraftVillage.algorithm_reference import fit_camera,compare
from harness.L3.MinecraftVillage.algorithm_workflow import make_workflow,diagnose,door_walk_plan,diagnose_doors


def replay_timeout(plan):
    # Allow slow headless rendering without changing simulation steps or scoring.
    seconds=sum(max(0.,float(step.get('seconds',0))) for step in plan['steps'])
    return max(3600,int(seconds*12+900))

def capture(run,trial,output,retry_capture=None,retry_episodes=None):
    started=time.monotonic();r=read_json(run/'run.json')
    if r.get('status') not in {'measured','collected'}:raise ValueError('Base independent verification incomplete')
    if r['source_sha256']!=tree_digest(trial/'workspace/project'):raise ValueError('Candidate changed')
    project=run/'workspace/project';before=tree_digest(project)
    if before!=r['verification_source_sha256']:raise ValueError('Verifier project changed')
    if bool(retry_capture)!=bool(retry_episodes):raise ValueError('Both retry evidence directories are required')
    if retry_capture:
        previous=read_json(retry_capture/'capture.json')
        if previous.get('source_sha256')!=r['source_sha256'] or previous.get('run_sha256')!=digest(run/'run.json'):
            raise ValueError('Retry capture source/verification identity mismatch')
    output.mkdir(parents=True,exist_ok=True)
    workspace=run/'workspace';sub=workspace/'algorithm-v1';sub.mkdir(exist_ok=False)
    export=read_json(workspace/'episodes/views/scene_geometry.json')
    bindings=read_json(run/'calibrated-bindings.json')
    ann=run/'reference-annotations.json'
    fit=fit_camera(export,read_json(ann),bindings);write_json(output/'camera-fit.json',fit)
    plans={};meta={}
    if fit['status']=='fitted':plans['fitted_reference']=fit['plan']
    plans['door_walk'],meta['door_walk']=door_walk_plan(bindings)
    try:
        plans['workflow'],meta['workflow']=make_workflow(export,bindings,read_json(workspace/'episodes/views/initial.json'))
    except (ValueError,KeyError) as error:
        write_json(output/'workflow.json',{'status':'planner_unresolved','reason':str(error),'workflow_success':None})
    write_json(output/'plan-metadata.json',meta)
    engine_sources=[x.split('src=',1)[1].split(',dst=',1)[0] for x in r['command'] if x.startswith('type=bind,src=') and '/engines/' in x]
    from tools.prepare_l3_trial import assert_engine_available
    for source in engine_sources:assert_engine_available(Path(source).resolve())
    name=r['container'];status={'status':'starting','source_sha256':r['source_sha256'],'run_sha256':digest(run/'run.json'),'episodes':{}}
    write_json(output/'capture.json',status)
    try:
        subprocess.run(['docker','start',name],check=True,stdout=subprocess.DEVNULL,timeout=180)
        for key,plan in plans.items():
            write_json(sub/(key+'-plan.json'),plan);status['status']='episode_'+key;write_json(output/'capture.json',status)
            timeout=replay_timeout(plan);budget_evidence=[]
            if retry_capture:
                from harness.L3.Suite.replay_budget import retry_budget
                timeout,budget_evidence=retry_budget(plan,retry_episodes,key,retry_capture/(key+'.log'),replay_folders=[retry_episodes/key])
            write_json(output/(key+'-walltime-budget.json'),{'timeout_seconds':timeout,'evidence':budget_evidence})
            command=['docker','exec',name,'python3','/opt/l3-public/ue.py','preview','/workspace/project','--output',
                '/workspace/algorithm-v1/'+key,'--plan','/workspace/algorithm-v1/'+key+'-plan.json','--timeout',str(timeout)]
            t=time.monotonic()
            from tools.l3_capture_reuse import reuse_episode
            reused = bool(retry_capture) and reuse_episode(previous,retry_episodes,sub/key,key,plan)
            with (output/(key+'.log')).open('xb') as log:
                if reused:
                    log.write(b"Reused completed identical-plan independent episode after full evidence hash verification.\n")
                    rc=0
                else:
                    rc=subprocess.run(command,stdout=log,stderr=log,timeout=timeout+120).returncode
            folder=sub/key
            if rc or not (folder/'completed.json').exists():
                status['episodes'][key]={'status':'infrastructure_failure','return_code':rc}
                write_json(output/(key+'.json'),{'status':'infrastructure_failure','return_code':rc});continue
            status['episodes'][key]={'status':'measured','seconds':time.monotonic()-t,**({'reused_from':str(retry_episodes/key),'original_seconds':previous['episodes'][key].get('seconds'),'evidence_hashes_verified':True} if reused else {})}
            if key=='door_walk':write_json(output/'door-walk.json',diagnose_doors(folder,meta[key]))
            elif key=='workflow':write_json(output/'workflow.json',diagnose(folder,meta[key]))
            elif key=='fitted_reference':
                groups=next(s['groups'] for s in plan['steps'] if s['op']=='instance_masks')
                pose=read_json(folder/'reference_pose.json')['camera'];mask_pose=read_json(folder/'mask_pose.json')['camera']
                if pose!=mask_pose:raise ValueError('Fitted RGB/mask camera mismatch')
                compare(trial/'workspace/input/reference.jpg',folder/'reference_rgb.png',folder/'reference_mask.png',ann,groups,output/'reference-fitted')
        # Submitted view is retained with the identical metric, not overwritten.
        ref=workspace/'episodes/reference';groups=read_json(run/'mask-palette.json')['groups']
        compare(trial/'workspace/input/reference.jpg',ref/'reference_rgb.png',ref/'reference_mask.png',ann,groups,output/'reference-submitted')
        if tree_digest(project)!=before or tree_digest(trial/'workspace/project')!=r['source_sha256']:
            raise ValueError('Candidate or verifier source changed')
        status.update(status='measured',elapsed_seconds=time.monotonic()-started,
            evidence_sha256={str(p.relative_to(run)):digest(p) for p in sub.rglob('*') if p.is_file() and p.suffix in {'.json','.png'}},
            before_project_sha256=before,after_project_sha256=tree_digest(project))
        write_json(output/'capture.json',status)
    except Exception as error:
        status.update(status='failed',error=str(error));write_json(output/'capture.json',status);raise
    finally:subprocess.run(['docker','stop','--time','10',name],capture_output=True,timeout=30)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ['run','trial','output']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--retry-capture',type=Path);p.add_argument('--retry-episodes',type=Path)
    a=p.parse_args();capture(a.run.resolve(),a.trial.resolve(),a.output.resolve(),a.retry_capture.resolve() if a.retry_capture else None,a.retry_episodes.resolve() if a.retry_episodes else None)
