"""External process/container control for L2 read-only Blender evidence and renders."""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
import uuid

from harness.L2.audit import compare_images
from src.evaluator.l2_case_compare import align_evaluated_roundoff
from .runtime import run_process
from .tasks import PROJECT, regular, sha256, write_json


class InvalidGeometryError(ValueError):
    """Non-finite native mesh geometry, distinct from an infrastructure timeout."""


def command(scene, output, blender, *, image, runtime, views=None):
    cpus = min(8,len(os.sched_getaffinity(0)))
    worker = PROJECT/'src/evaluator/l2_case_blender.py'
    collector = PROJECT/'src/evaluator/l2_case_collector.py'
    options = ['--background','--factory-startup','--disable-autoexec','--threads',str(cpus),
               '--python-exit-code','1','--python',str(worker),'--',
               '--scene',str(scene),'--output',str(output/'facts.json')]
    if runtime == 'local':
        if views is not None:
            options += ['--views',str(output.parent/'views.json')]
        return [str(blender),*options],None
    if runtime != 'docker':
        raise ValueError('Unknown L2 inspection runtime')
    name = '3dbench-l2-inspect-'+uuid.uuid4().hex
    options[options.index('--python')+1] = '/worker/l2_case_blender.py'
    options[options.index('--scene')+1] = '/work/'+scene.name
    options[options.index('--output')+1] = '/audit/facts.json'
    mounts = [(scene.parent,'/work',True),(output,'/audit',False),
              (worker,'/worker/l2_case_blender.py',True),(collector,'/worker/l2_case_collector.py',True),
              (PROJECT/'src/evaluator/l2_case_dense.py','/worker/l2_case_dense.py',True),
              (PROJECT/'src/evaluator/l2_native_physics.py','/worker/l2_native_physics.py',True),
              (PROJECT/'src/evaluator/l2_material_policy.py','/worker/l2_material_policy.py',True),
              (PROJECT/'src/evaluator/l2_visible_surface.py','/worker/l2_visible_surface.py',True),
              (PROJECT/'src/evaluator/l2_mesh_order.py','/worker/l2_mesh_order.py',True),
              (blender.parent,'/opt/blender',True)]
    if views is not None:
        mounts.append((output.parent/'views.json','/views.json',True))
        options += ['--views','/views.json']
    # Rotate the affinity window: a fixed [:cpus] slice pins every concurrent
    # inspection onto the same first cores, starving them while the rest idle.
    allowed = sorted(os.sched_getaffinity(0))
    offset = (os.getpid() * cpus) % len(allowed)
    cpu_set = ','.join(str(c) for c in sorted({allowed[(offset + i) % len(allowed)] for i in range(cpus)}))
    args = ['docker','run','--rm','--name',name,'--network','none','--read-only',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','512',
            '--memory','8g','--cpus',str(cpus),'--cpuset-cpus',cpu_set,'--user',f'{os.getuid()}:{os.getgid()}',
            '--tmpfs','/tmp:rw,size=1g,mode=1777','--env','HOME=/tmp','--env',f'OMP_NUM_THREADS={cpus}',
            '--env','OPENBLAS_NUM_THREADS=2']
    for source,target,readonly in mounts:
        args += ['--mount',f'type=bind,src={source.resolve()},dst={target}'+(',readonly' if readonly else '')]
    return [*args,'--workdir','/work',image,*options],name


def inspect_scene(scene, directory, blender, *, runtime, image, deadline, timeout, views=None):
    directory.mkdir(parents=True,exist_ok=False)
    output = directory/'output'
    output.mkdir()
    scene = regular(scene.parent,scene.name)
    before = sha256(scene)
    if views is not None:
        write_json(directory/'views.json',views)
    args,container = command(scene,output,blender,image=image,runtime=runtime,views=views)
    process = run_process(args,cwd=directory,directory=directory/'process',deadline=deadline,
                          timeout=timeout,container=container)
    if process['status'] != 'success':
        if (output/'error.json').is_file():
            detail=json.loads((output/'error.json').read_text())
            if detail.get('code')=='nonfinite_geometry':
                raise InvalidGeometryError(detail['message'])
        raise RuntimeError('L2 inspection '+process['status']+': '+str(directory/'process/process.json'))
    if sha256(scene) != before:
        raise ValueError('Native scene changed during read-only inspection')
    facts = json.loads(regular(output,'facts.json').read_text())
    if not isinstance(facts.get('scene'),dict):
        raise ValueError('Missing scene facts')
    facts['geometry_root'] = str(output)
    return facts


def reproduce(output, facts, directory, blender, *, runtime, image, deadline, timeout, limit=8, baseline=None):
    """Match submitted pixels to distinct saved cameras, without author-name requirements."""
    all_cameras = facts['scene']['cameras']
    cameras = sorted(all_cameras)
    if baseline is not None:
        # Public edit contracts fix the original primary camera and a 0.30 m
        # local-X alternate. Existing unrelated cameras must stay in the scene.
        primary = baseline['scene']['active_camera']
        if primary not in all_cameras:
            return {'passed':False,'status':'failed','reason':'Original edit camera missing'}
        from src.evaluator.l2_case_metrics import camera_pair
        from src.evaluator.spec import CheckSpec
        check = CheckSpec.parse({'id':'selection','metric':'l2_case_camera_pair','group':'camera',
            'params':{'mode':'local_translation','delta_m':.30,'tolerance':.003}})
        cameras = [primary] + [name for name in cameras if name != primary and
            camera_pair(check,{'scene':{'cameras':{'__main':all_cameras[primary],'__alternate':all_cameras[name]}}},None)[0] == 1]

    if len(cameras) < 2 or len(cameras) > limit:
        return {'passed':False,'status':'not_measurable','reason':f'Need 2..{limit} saved cameras for bounded matching',
                'camera_count':len(cameras)}
    render = facts['scene']['render']
    size = [round(x*render['resolution_percentage']/100) for x in render['resolution']]
    views = [{'camera':camera,'artifact':f'camera-{i}.png','resolution':size} for i,camera in enumerate(cameras)]
    rendered = inspect_scene(output/'scene.blend',directory,blender,runtime=runtime,image=image,
                             deadline=deadline,timeout=timeout,views=views)
    # Worker observations must be repeatable before matching either image.
    stable = lambda scene: {k:v for k,v in scene.items() if k not in {'mesh_contacts','collision_pairs','visible_surface'}}
    comparable,roundoff = align_evaluated_roundoff(rendered['scene'],facts['scene'],directory=rendered.get('geometry_root'),reference_directory=facts.get('geometry_root'))
    if stable(comparable) != stable(facts['scene']):
        return {'passed':False,'status':'failed','reason':'Inspection facts changed between opens'}
    comparisons = {artifact:[compare_images(output/artifact,directory/'output'/v['artifact'],.01,.05) for v in views]
                   for artifact in ('main.png','alternate.png')}
    choices = list(itertools.permutations(range(len(cameras)),2))
    def error(pair):
        return sum(comparisons[name][index].get('mean_error',1000) for name,index in zip(comparisons,pair))
    pair = min(choices,key=error)
    chosen = {name:{'camera':cameras[index],**comparisons[name][index],
                   'render_path':str(directory/'output'/views[index]['artifact'])} for name,index in zip(comparisons,pair)}
    result = {'passed':all(v['passed'] for v in chosen.values()),'status':'measured','views':chosen,
              'evaluated_roundoff':roundoff,'camera_count':len(cameras),'saved_camera_count':len(all_cameras),'selection':'Minimum decoded-pixel error over distinct saved-camera pairs'}
    write_json(directory/'comparison.json',result)
    return result


def reproduce_flexible(output, facts, directory, blender, *, runtime, image, deadline, timeout, baseline=None,
                       artifacts=('main.png','alternate.png')):
    """Find a genuine saved-camera pair without rejecting unrelated saved cameras.

    Start with likely main/alternate cameras, then search the remainder in bounded
    groups under one total timeout. Camera pose is a quality check, not eligibility.
    """
    all_cameras=facts['scene']['cameras']
    old=(baseline or {}).get('scene',{})
    preferred=[old.get('active_camera'),facts['scene'].get('active_camera')]
    preferred+=sorted(set(all_cameras)-set(old.get('cameras',{}))) if baseline else []
    cameras=list(dict.fromkeys(name for name in [*preferred,*sorted(all_cameras)] if name in all_cameras))
    if len(set(artifacts)) != len(artifacts) or len(artifacts) not in (2,3):
        raise ValueError('Two or three distinct authored image artifacts required')
    count=len(artifacts)
    if len(cameras)<count:
        return {'passed':False,'status':'not_measurable','reason':'Two distinct saved cameras are required',
            'camera_count':len(cameras),'protocol':'l2-camera-search-v2'}
    end=min(deadline,time.monotonic()+timeout)
    render=facts['scene']['render']
    size=[round(x*render['resolution_percentage']/100) for x in render['resolution']]
    stable=lambda scene:{k:v for k,v in scene.items() if k not in {'mesh_contacts','collision_pairs','visible_surface'}}
    comparisons={name:[] for name in artifacts}
    inspected=[];roundoffs=[];chosen={}
    groups=[cameras[:count],*[cameras[i:i+8] for i in range(count,len(cameras),8)]]
    directory.mkdir(parents=True,exist_ok=False)
    for index,group in enumerate(groups):
        remaining=end-time.monotonic()
        if remaining<=0:raise TimeoutError('Saved-camera verification budget exhausted')
        folder=directory/f'camera-batch-{index:03d}'
        views=[{'camera':name,'artifact':f'camera-{i}.png','resolution':size} for i,name in enumerate(group)]
        rendered=inspect_scene(output/'scene.blend',folder,blender,runtime=runtime,image=image,
            deadline=end,timeout=remaining,views=views)
        comparable,roundoff=align_evaluated_roundoff(rendered['scene'],facts['scene'],
            directory=rendered.get('geometry_root'),reference_directory=facts.get('geometry_root'))
        if stable(comparable)!=stable(facts['scene']):
            return {'passed':False,'status':'failed','reason':'Inspection facts changed between opens',
                'protocol':'l2-camera-search-v2'}
        roundoffs.append(roundoff)
        for view in views:
            inspected.append(view['camera'])
            path=folder/'output'/view['artifact']
            for name in comparisons:
                comparisons[name].append({'camera':view['camera'],
                    **compare_images(output/name,path,.01,.05),'render_path':str(path)})
        pairs=itertools.permutations(range(len(inspected)),count)
        def rank(pair):
            selected=[comparisons[name][i] for name,i in zip(comparisons,pair)]
            return (not all(v['passed'] for v in selected),sum(v.get('mean_error',1000) for v in selected))
        pair=min(pairs,key=rank)
        chosen={name:comparisons[name][i] for name,i in zip(comparisons,pair)}
        if all(v['passed'] for v in chosen.values()):break
    result={'passed':all(v['passed'] for v in chosen.values()),'status':'measured','views':chosen,
        'evaluated_roundoff':roundoffs,'camera_count':len(inspected),'saved_camera_count':len(all_cameras),
        'protocol':'l2-camera-search-v2','required_artifacts':list(artifacts),
        'selection':'Verified distinct saved cameras; prioritized then batched, no content-pose filter'}
    write_json(directory/'comparison.json',result)
    return result
