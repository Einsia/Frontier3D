"""Finish existing independent capture before separate dense-geometry analysis.

Preserves the original collector record. Stops only the named collector after
all its planned episodes have completed; never stops a shared Docker service.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness.L3.MinecraftVillage.protocol import read_json,write_json,digest,tree_digest


def complete(run,trial,pid):
    while True:
        r=read_json(run/'run.json')
        if r.get('status')=='measured':return
        episodes=r.get('episodes',{})
        resource_done=episodes.get('resource_chain',{}).get('completed') or 'resource_chain' in r.get('submission_contract_failures',{})
        if episodes.get('reference',{}).get('completed') and resource_done:break
        if r.get('status')=='failed':raise RuntimeError('Collector failed before finishing captures: '+str(r.get('error')))
        time.sleep(2)
    workspace=run/'workspace'
    for key,value in r['episodes'].items():
        if not value.get('completed') or not read_json(workspace/'episodes'/key/'completed.json').get('completed'):
            raise ValueError('Incomplete planned episode '+key)
    if tree_digest(trial/'workspace/project')!=r['source_sha256'] or tree_digest(workspace/'project')!=r['verification_source_sha256']:
        raise ValueError('Source changed during collection')
    proc=Path('/proc')/str(pid)/'cmdline'
    if proc.exists():
        cmd=proc.read_bytes().decode(errors='replace')
        if 'verify_l3_submission.py' not in cmd or str(run) not in cmd:raise ValueError('Collector PID identity mismatch')
        os.kill(pid,signal.SIGTERM)
    subprocess.run(['docker','stop','--time','10',r['container']],check=True,capture_output=True)
    write_json(run/'collector-original-run.json',r)
    ref=workspace/'episodes/reference';plan=read_json(workspace/'plans/reference.json')
    event=read_json(ref/'reference_ids_event.json')
    if not event.get('accepted'):raise ValueError('Reference masks failed')
    pose=read_json(ref/'reference_pose.json')['camera']
    if pose!=read_json(ref/'mask_pose.json')['camera']:raise ValueError('RGB/mask pose mismatch')
    reference=trial/'workspace/input/reference.jpg'
    write_json(run/'reference-view.json',{'protocol':'joint_scene_camera_prediction','evaluator_rendered':True,
        'candidate_sha256':digest(ref/'reference_rgb.png'),'reference_sha256':digest(reference),'camera':pose,'posthoc_alignment':False})
    groups=next(s['groups'] for s in plan['steps'] if s['op']=='instance_masks')
    write_json(run/'mask-palette.json',{'groups':groups,'camera':pose,'color_encoding':'ue_srgb_linear_display_gamma_2_2',
        'candidate_sha256':digest(ref/'reference_rgb.png'),'mask_sha256':digest(ref/'reference_mask.png'),
        'nonopaque_components':event.get('nonopaque_components',[])})
    repo=Path(__file__).resolve().parents[1]
    annotation=repo/'benchmarks/l3/reference/minecraft-visible-v1-provisional.json'
    write_json(run/'reference-annotations.json',read_json(annotation))
    r.update(status='collected',geometry_status='separate_algorithm_worker',
        collection_completion={'reason':'Dense static geometry uses certified box-union compaction before analysis',
                               'collector_pid':pid,'completed_unix':time.time()},
        evidence_sha256={str(p.relative_to(run)):digest(p) for p in (workspace/'episodes').rglob('*') if p.is_file() and p.suffix in {'.json','.png'}})
    write_json(run/'run.json',r);print(json.dumps({'status':'collected','episodes':len(r['episodes'])}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--trial',type=Path,required=True);p.add_argument('--pid',type=int,required=True)
    a=p.parse_args();complete(a.run.resolve(),a.trial.resolve(),a.pid)
