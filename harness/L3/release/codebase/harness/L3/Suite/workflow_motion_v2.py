"""Check the replayed workflow's sampled geometry, alongside unchanged local tests."""
import os,time,concurrent.futures,traceback
from .policy import ROOT,read,write
from .reference_review import OUT
from .observations import changed
from harness.L3.MinecraftVillage.scene_geometry import Scene,motion_measure

def measure(old):
    slug=old.parent.name.removeprefix('suite-').removesuffix('-v1')
    folder=OUT/old.name/('gpt-6-'+slug)/'workflow-replay'
    if (folder/'motion.json').exists():return
    deadline=time.time()+2400
    while (not (folder/'interaction-observations.json').exists() or not (folder.parent/'physical/physical-summary.json').exists()) and time.time()<deadline:time.sleep(5)
    observed=read(folder/'interaction-observations.json')
    episode=__import__('pathlib').Path(observed['workflow_episode'])
    original=read(old/'physical-scene.json')
    visible={**original,'instances':[x for x in original['instances'] if x.get('visible',True) and x.get('role')!='water']}
    scene=Scene(visible,open_surface_fallback=True)
    targets=list(read(OUT/old.name/('gpt-6-'+slug)/'physical/physical-summary.json')['motion']['targets'])
    slices=folder/'motion-episodes';slices.mkdir(exist_ok=True)
    for target in targets:
        dest=slices/target.replace('.','_');dest.mkdir(exist_ok=True)
        for source in (old/'motion-episodes'/target.replace('.','_')).glob('*.json'):
            if source.name.startswith('trajectory_w_'):continue
            path=dest/source.name
            if not path.exists():os.link(source,path)
    initial=read(episode/'initial.json');previous={t:initial for t in targets}
    for source in sorted(episode.glob('trajectory_*.json')):
        frame=read(source)
        for target in targets:
            if not changed(previous[target],frame,target):continue
            dest=slices/target.replace('.','_')/('trajectory_w_'+source.stem+'.json')
            if not dest.exists():os.link(source,dest)
            previous[target]=frame
    rows={}
    for target in targets:
        final=slices/target.replace('.','_')/'trajectory_w_zz_final.json'
        if not final.exists():os.link(episode/'final.json',final)
        result=folder/'motion-targets'/(target+'.json')
        if not result.exists():write(result,motion_measure(scene,slices,targets=[target],stop_on_failure=True,rigid_assemblies=True)['targets'][target])
        rows[target]=read(result)
        write(folder/'motion-progress.json',{'completed':len(rows),'total':len(targets),'time':time.time()})
    write(folder/'motion.json',{'targets':rows,'episodes':str(slices),'scope':'All recorded poses in independent local tests and replayed real workflow; discrete sampling.'})

def main():
    tasks=[]
    for p in (ROOT/'data/l3/evaluations').glob('suite-*-v1/l3-*/workflow-metadata.json'):
        if any(r['reason']=='operation outside public contract' for r in read(p).get('rejected',[])):tasks.append(p.parent)
    errors={};done=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs={pool.submit(measure,p):str(p) for p in tasks}
        for future in concurrent.futures.as_completed(jobs):
            key=jobs[future]
            try:future.result();done.append(key)
            except Exception as exc:errors[key]=str(exc);traceback.print_exc()
            write(OUT/'workflow-motion-progress.json',{'completed':done,'errors':errors,'total':len(tasks),'time':time.time()})
if __name__=='__main__':main()
