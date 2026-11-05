"""Replay editable-block tests using observed post-removal target geometry."""
import argparse,json,subprocess,time,sys,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest,tree_digest,local_plan,BLOCKS
from harness.L3.MinecraftVillage.geometry_routes import retarget_removed_block
from harness.L3.MinecraftVillage.inventory import local as inventory_local
from tools.verify_l3_submission import diagnose_local


def refine(trial,run):
    o=trial/'evaluation-algorithm-v1/runtime-geometry-v2';r=read_json(o/'run.json');base=read_json(run/'run.json')
    if r['status']!='measured':raise ValueError('Runtime collection must be complete')
    if r['source_sha256']!=tree_digest(trial/'workspace/project') or r['verification_source_sha256']!=tree_digest(run/'workspace/project'):raise ValueError('Source changed')
    sub=run/'workspace/runtime-geometry-v2';bindings=read_json(o/'bindings.json')
    engines=[x.split('src=',1)[1].split(',dst=',1)[0] for x in base['command'] if x.startswith('type=bind,src=') and '/engines/' in x]
    for cid in subprocess.check_output(['docker','ps','-q'],text=True).split():
        info=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
        if any(m['Source'] in engines for m in info['Mounts']):raise ValueError('Engine busy')
    archive=o/'block-aim-revision';archive.mkdir(exist_ok=False);shutil.copy2(o/'run.json',archive/'run.json')
    started=time.monotonic();container=base['container']
    try:
        subprocess.run(['docker','start',container],check=True,stdout=subprocess.DEVNULL)
        for target in BLOCKS:
            key=target.replace('.','_');capture=key+'_retargeted';snapshot=sub/key/'after_1.json'
            if (sub/capture).exists():raise ValueError('Capture already exists')
            p,audit=retarget_removed_block(local_plan(target,bindings['entities'][target]),read_json(snapshot),target)
            audit.update(snapshot=str(snapshot),snapshot_sha256=digest(snapshot))
            write_json(o/(key+'-retarget.json'),audit);write_json(sub/(capture+'-plan.json'),p)
            r['status']='episode_'+capture;write_json(o/'run.json',r);t=time.monotonic()
            cmd=['docker','exec',container,'python3','/opt/l3-public/ue.py','preview','/workspace/project','--output','/workspace/runtime-geometry-v2/'+capture,'--plan','/workspace/runtime-geometry-v2/'+capture+'-plan.json','--timeout','1200']
            with (o/(capture+'.log')).open('x') as f:rc=subprocess.run(cmd,stdout=f,stderr=f,timeout=1300).returncode
            folder=sub/capture
            if rc or not read_json(folder/'completed.json').get('completed'):raise RuntimeError('Capture failed '+capture)
            r['episodes'][capture]={'completed':True,'seconds':time.monotonic()-t}
            r['episodes'][key].update(evaluation_episode=capture,diagnostics=diagnose_local(folder,p,bindings['entities'][target]),inventory=inventory_local(folder,target,required=True))
            write_json(o/'run.json',r)
        if r['source_sha256']!=tree_digest(trial/'workspace/project') or r['verification_source_sha256']!=tree_digest(run/'workspace/project'):raise ValueError('Source changed')
        r['elapsed_seconds']+=time.monotonic()-started
        r.update(status='measured',evidence_sha256={str(p.relative_to(run)):digest(p) for p in sub.rglob('*') if p.is_file() and p.suffix in {'.json','.png'}},diagnostics_sha256={p.name:digest(p) for p in o.glob('*.json') if p.name not in {'run.json','effective-run.json','effective-geometry.json'}})
        write_json(o/'run.json',r)
    except Exception as e:
        r.update(status='failed',error=str(e));write_json(o/'run.json',r);raise
    finally:subprocess.run(['docker','stop','--time','10',container],capture_output=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--trial',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    a=p.parse_args();refine(a.trial.resolve(),a.run.resolve())
