"""Explicit finite evaluation batch. Does not generate candidates or schedule jobs."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest


def batch(jobs_path,provider):
    root=Path(__file__).resolve().parents[1];python=str(root/'.venv/bin/python')
    jobs=read_json(jobs_path)['jobs'];status_path=jobs_path.with_name('batch-progress.json')
    statuses=[]
    for job in jobs:
        trial,run,output=map(Path,[job['trial'],job['run'],job['output']])
        state={'trial':str(trial),'status':'waiting_for_collection'};statuses.append(state)
        write_json(status_path,{'jobs':statuses})
        while read_json(run/'run.json')['status'] not in {'collected','measured'}:
            r=read_json(run/'run.json')
            if r['status']=='failed':raise RuntimeError('Independent collection failed: '+str(r.get('error')))
            time.sleep(5)
        child=None
        if not (output/'visual/summary.json').exists():
            args=[python,'-m','harness.L3.MinecraftVillage.algorithm_judge','--run',str(run),'--trial',str(trial),
                  '--output',str(output/'visual'),'--provider',str(provider)]
            with (output/'visual.log').open('xb') as log:child=subprocess.Popen(args,cwd=root,stdout=log,stderr=log)
            state['judge_pid']=child.pid
        state['status']='capturing_camera_and_workflow';write_json(status_path,{'jobs':statuses})
        if not (output/'capture/capture.json').exists():
            args=[python,str(root/'tools/capture_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(output/'capture')]
            with (output/'capture.log').open('xb') as log:
                completed=subprocess.run(args,cwd=root,stdout=log,stderr=log)
            state['capture_returncode']=completed.returncode
        if child:state['judge_returncode']=child.wait()
        geometry=output/'geometry/geometry.json'
        while not geometry.exists():
            launch=read_json(output/'geometry-launch.json')
            if not Path('/proc',str(launch['pid'])).exists():raise RuntimeError('Geometry worker exited without result')
            time.sleep(5)
        if read_json(geometry)['geometry_sha256']!=digest(run/'workspace/episodes/views/scene_geometry.json'):
            raise ValueError('Geometry result belongs to different evidence')
        runtime=output/'runtime-geometry-v2'
        state['status']='measuring_geometry_based_interactions';write_json(status_path,{'jobs':statuses})
        if not (runtime/'run.json').exists():
            with (output/'runtime-repair.log').open('xb') as log:
                measured=subprocess.run([python,str(root/'tools/repair_l3_runtime.py'),'--trial',str(trial),'--run',str(run),'--output',str(runtime)],cwd=root,stdout=log,stderr=log)
            if measured.returncode:raise RuntimeError('Geometry-based interaction measurement failed')
        if read_json(runtime/'run.json').get('status')!='measured':raise RuntimeError('Interaction evidence is incomplete; refusing stale report')
        state['status']='reporting';write_json(status_path,{'jobs':statuses})
        with (output/'report.log').open('xb') as log:
            completed=subprocess.run([python,str(root/'tools/report_l3_algorithms.py'),'--run',str(run),'--trial',str(trial),'--output',str(output)],cwd=root,stdout=log,stderr=log)
        state.update(status='reported' if completed.returncode==0 else 'report_failed',report_returncode=completed.returncode)
        write_json(status_path,{'jobs':statuses})
    print(json.dumps({'status':'finished','jobs':statuses}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--jobs',type=Path,required=True);p.add_argument('--provider',type=Path,required=True)
    a=p.parse_args();batch(a.jobs.resolve(),a.provider.resolve())
