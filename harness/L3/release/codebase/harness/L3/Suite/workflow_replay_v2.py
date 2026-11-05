"""Replay rejected extension actions against the same frozen verifier project.

Only public observer operations are accepted. Extra registered actor actions
are candidate gameplay calls; their return strings never establish success.
"""
from pathlib import Path
import subprocess,json,os,time,concurrent.futures,traceback,copy,hashlib
import numpy as np
from .policy import ROOT,read,write,POLICY
from .reference_review import OUT
from .plans import workflow_plan
from .observations import goals,entities,pos
from harness.L3.MinecraftVillage.protocol import tree_digest,digest

def workflow_summary(old,episode,metadata,bindings):
    original=read(old/'interaction-observations.json');initial=read(episode/'initial.json');final=read(episode/'final.json');frames=[initial];walks=[]
    for row in metadata['steps']:
        a=read(episode/(row['before']+'.json'));b=read(episode/(row['after']+'.json'));frames.extend([a,b]);step=row['step']
        if step['op']=='walk_to':
            distance=float(np.linalg.norm(np.array(b.get('pawn_position_cm',[float('inf')]*3))-np.array(step['target_cm'])))
            walks.append({'name':step['name'],'distance_cm':distance if np.isfinite(distance) else None,'passed':distance<=POLICY['navigation_tolerance_cm']})
    frames.append(final);goal_rows=goals(old.name,initial,final,frames,bindings)
    resource=sum(x['passed'] for x in goal_rows)/len(goal_rows)
    route=sum(x['passed'] for x in walks)/len(walks) if walks else 0.
    flow=float(bool(goal_rows and all(x['passed'] for x in goal_rows) and walks and all(x['passed'] for x in walks) and not metadata['rejected']))
    door=original['door_walks'];nav=(route+sum(x['passed'] for x in door)/len(door))/2 if door else route
    return {**original,'goals':goal_rows,'resource_state':resource,'continuous_workflow':flow,'route_success_fraction':route,
            'walks':walks,'navigation':nav,'state_and_workflow':.5*resource+.5*flow,'rejected_route_steps':metadata['rejected'],
            'workflow_episode':str(episode),'workflow_policy':'Registered candidate action extensions allowed; only physical predicates and real pawn travel scored.'}

def replay(old):
    slug=old.parent.name.removeprefix('suite-').removesuffix('-v1');output=OUT/old.name/('gpt-6-'+slug)/'workflow-replay';output.mkdir(parents=True,exist_ok=True)
    if (output/'interaction-observations.json').exists():return
    workspace=old/'workspace';bindings=read(old/'executable-bindings.json') if (old/'executable-bindings.json').exists() else read(workspace/'project/bindings.json')
    observed=entities(read(workspace/'episodes/workflow/initial.json'))
    plan,meta=workflow_plan(bindings,read(old/'contract.json'),observed_ids=observed)
    write(output/'workflow-metadata.json',meta);write(output/'plan.json',plan)
    plan_path=workspace/'plans/workflow-extensions-v2.json';write(plan_path,plan)
    episode=workspace/'episodes/workflow-extensions-v2'
    previous=read(old/'source.json');record=read(old/'run.json');name=record['container']
    info=json.loads(subprocess.run(['docker','inspect',name],check=True,capture_output=True).stdout)[0]
    mounts={m['Destination']:m['Source'] for m in info['Mounts']}
    if mounts.get('/workspace')!=str(workspace):raise ValueError('Wrong verifier workspace')
    if info['State']['Running']:raise RuntimeError('Verifier container already in use')
    before=tree_digest(workspace/'project')
    if before!=previous['verification_source_sha256']:raise ValueError('Verifier source changed')
    status={'status':'starting','container':name,'source_sha256':previous['source_sha256'],'verification_source_sha256':before,'started_unix':time.time()}
    write(output/'run.json',status)
    try:
        subprocess.run(['docker','start',name],check=True,capture_output=True)
        if not (episode/'completed.json').exists():
            if episode.exists():episode.rename(episode.with_name(episode.name+'-failed-'+str(time.time_ns())))
            timeout=max(1800,int(sum(min(30,float(s.get('seconds',0))) for s in plan['steps'])*4+600))
            command=['docker','exec',name,'python3','/opt/l3-public/ue.py','preview','/workspace/project',
                     '--output','/workspace/episodes/workflow-extensions-v2','--plan','/workspace/plans/workflow-extensions-v2.json','--timeout',str(timeout)]
            status['status']='executing';write(output/'run.json',status)
            with (output/'runtime.log').open('ab') as log:
                completed=subprocess.run(command,stdout=log,stderr=log,timeout=timeout+60)
            if completed.returncode:raise RuntimeError('Workflow replay failed; see runtime.log')
        if not read(episode/'completed.json')['completed']:raise RuntimeError('Incomplete physical trajectory')
        if tree_digest(workspace/'project')!=before:raise ValueError('Verifier project changed during replay')
        result=workflow_summary(old,episode,meta,bindings);write(output/'interaction-observations.json',result)
        status.update(status='completed',completed_unix=time.time(),evidence={p.name:digest(p) for p in episode.glob('*.json')})
        write(output/'run.json',status)
    except Exception as exc:
        status.update(status='failed',error=str(exc));write(output/'run.json',status);raise
    finally:subprocess.run(['docker','stop','--time','10',name],capture_output=True)

def main():
    tasks=[]
    for p in (ROOT/'data/l3/evaluations').glob('suite-*-v1/l3-*/workflow-metadata.json'):
        if any(r['reason']=='operation outside public contract' for r in read(p).get('rejected',[])):tasks.append(p.parent)
    # Prefer the user's reported kitchen/orchard cases first, without changing tests.
    tasks.sort(key=lambda p:(p.name not in {'l3-e01','l3-e04'},str(p)))
    done=[];errors={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs={pool.submit(replay,p):str(p) for p in tasks}
        for job in concurrent.futures.as_completed(jobs):
            key=jobs[job]
            try:job.result();done.append(key);print('workflow complete',key,flush=True)
            except Exception as exc:errors[key]=str(exc);traceback.print_exc()
            write(OUT/'workflow-progress.json',{'completed':done,'errors':errors,'total':len(jobs),'updated_unix':time.time()})
if __name__=='__main__':main()
