"""Measure newly executed candidates using frozen linear visual requirements."""
import os

from copy import deepcopy

from dataclasses import replace

import fcntl

import hashlib

import json

import os

from pathlib import Path

import shutil

import subprocess

import sys

import tempfile

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))

from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import numpy as np

from PIL import Image

from harness.L2.vlm_judge import JudgeConfig, judge_task

from src.agent_judge.protocol import read_json, write_json, digest

from src.evaluator.linear_visual import VERSION, IMAGE_WEIGHTS, aggregate, variant_components

from src.evaluator.l2_reference_regions import regional_components

from src.evaluator.l2_reference_image import appearance_components

from src.evaluator.l1_l2_alignment import measure_data

from tools.run_l1_strict_review import collect_native, system_gates, flatten, BLENDER

from benchmark.compat import checked, now

from benchmark.compat import classify

from tools.scene_render import render

def pin(path, expected=None):
    path = Path(path).resolve(strict=True)
    sha = digest(path)
    if expected and expected != sha:
        raise ValueError('Candidate evidence changed: '+str(path))
    return {'path': str(path), 'sha256': sha}

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    write_json(temporary, value)
    os.replace(temporary, path)

def archive_preflight_failure(folder):
    """A failed packet setup made no API call and has no response to select."""
    if not (folder/'run.json').exists():return
    record = read_json(folder/'run.json')
    if not record.get('attempts') and record.get('status')=='not_measurable':
        archived = folder.with_name(folder.name+'-preflight-'+digest(folder/'run.json')[:12])
        folder.rename(archived)

def implementation_binding(root):
    files=[*sorted((ROOT/'src/agent_judge').glob('*.py')),*sorted((ROOT/'src/evaluator').glob('*.py')),
        ROOT/'harness/L2/vlm_judge.py',Path(__file__),ROOT/'tools/scene_render.py',ROOT/'tools/run_l1_strict_review.py']
    hashes={str(p.relative_to(ROOT)):digest(p) for p in files}
    identity=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
    folder=root/'implementation_snapshots'/identity
    if not (folder/'manifest.json').exists():
        for relative,expected in hashes.items():
            destination=folder/relative;destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/relative,destination)
            if digest(destination)!=expected:raise ValueError('Implementation changed while freezing')
        atomic(folder/'manifest.json',{'files':hashes,'sha256':identity})
    return pin(folder/'manifest.json')

def tracked_camera_fallback(artifacts, native, folder, worker):
    """Only a hash-bound keyframed parent/constraint refusal permits fallback."""
    from src.evaluator.tracked_camera_export_blender import KEYFRAMED_SHA256
    if worker.name!='keyframed_camera_export_blender.py' or digest(worker)!=KEYFRAMED_SHA256:
        raise ValueError('Tracked fallback requires the pinned keyframed worker')
    if (folder/'result.json').exists():raise ValueError('Accepted export result must not be replaced')
    request={'native':artifacts['scene.blend'],'export':artifacts['scene.glb'],
             'frame':1,'active_camera':native['active_camera'],'output':str(folder),
             'request_path':str(folder/'request.json')}
    if read_json(folder/'request.json')!=request:raise ValueError('Failed export request changed')
    for pointer in (request['native'],request['export']):pin(pointer['path'],pointer['sha256'])
    log=(folder/'worker.log').read_text(errors='replace')
    if 'ValueError: Camera parent or constraints require a separate adapter' not in log:
        raise ValueError('Tracked fallback requires the explicit camera dependency refusal')
    if folder.parent.name!='export-keyframed':raise ValueError('Tracked fallback requires an isolated keyframed directory')
    return folder.parent.with_name('export-tracked')/folder.name

def light_tracked_fallback(artifacts,native,folder,worker):
    from src.evaluator.light_tracked_camera_export_blender import TRACKED_SHA256
    if worker.name!='tracked_camera_export_blender.py' or digest(worker)!=TRACKED_SHA256:
        raise ValueError('Light fallback requires the pinned tracked-camera worker')
    if (folder/'result.json').exists():raise ValueError('Accepted tracked result must not be replaced')
    request=dict(native=artifacts['scene.blend'],export=artifacts['scene.glb'],frame=1,
                 active_camera=native['active_camera'],output=str(folder),request_path=str(folder/'request.json'))
    if read_json(folder/'request.json')!=request:raise ValueError('Failed tracked request changed')
    for pointer in (request['native'],request['export']):pin(pointer['path'],pointer['sha256'])
    log=(folder/'worker.log').read_text(errors='replace')
    if ('ValueError: Animated/constrained native environment requires explicit baking: ' not in log
            or 'for obj in lights.values():base.check_static_object(obj)' not in log):
        raise ValueError('Light fallback requires the explicit tracked LIGHT constraint refusal')
    if folder.parent.name!='export-tracked':raise ValueError('Light fallback requires an isolated tracked directory')
    return folder.parent.with_name('export-light-tracked')/folder.name

def animated_light_fallback(artifacts,native,folder,worker):
    from src.evaluator.tracked_camera_export_blender import KEYFRAMED_SHA256
    if worker.name!='keyframed_camera_export_blender.py' or digest(worker)!=KEYFRAMED_SHA256:
        raise ValueError('Animated-light fallback requires the pinned keyframed worker')
    if (folder/'result.json').exists():raise ValueError('Accepted keyframed result must not be replaced')
    request=dict(native=artifacts['scene.blend'],export=artifacts['scene.glb'],frame=1,
                 active_camera=native['active_camera'],output=str(folder),request_path=str(folder/'request.json'))
    if read_json(folder/'request.json')!=request:raise ValueError('Failed keyframed request changed')
    for pointer in (request['native'],request['export']):pin(pointer['path'],pointer['sha256'])
    log=(folder/'worker.log').read_text(errors='replace')
    if ('ValueError: Animated/constrained native environment requires explicit baking: ' not in log
            or 'keyframed_camera_export_blender.py' not in log
            or 'in check_static_object' not in log or 'else:strict(obj)' not in log
            or 'ValueError: Camera ' in log):
        raise ValueError('Animated-light fallback requires the explicit keyframed environment refusal')
    if folder.parent.name!='export-keyframed':raise ValueError('Animated-light fallback requires an isolated keyframed directory')
    return folder.parent.with_name('export-animated-light')/folder.name

def addition_exported_scene(artifacts, native, folder, seed):
    """Use the same validated export adapter during collection and final replay."""
    legacy = folder/'export'/seed
    if (legacy/'result.json').exists():
        return exported_scene(artifacts, native, legacy)
    return exported_scene(artifacts, native, folder/'export-keyframed'/seed,
        worker=ROOT/'src/evaluator/keyframed_camera_export_blender.py', allow_tracked_camera=True)

def exported_scene(artifacts, native, folder, *, worker=None, allow_tracked_camera=False):
    try:
        return supported_exported_scene(artifacts, native, folder, worker=worker,
                                        allow_tracked_camera=allow_tracked_camera)
    except ValueError:
        if not allow_tracked_camera or not worker or worker.name != 'keyframed_camera_export_blender.py':
            raise
        from src.evaluator.tracked_camera_export_blender import KEYFRAMED_SHA256
        if digest(worker) != KEYFRAMED_SHA256:
            raise
        candidates = [folder, *(folder.parent.with_name(name)/folder.name for name in
                ('export-animated-light', 'export-tracked', 'export-light-tracked'))]
        if any((candidate/'result.json').exists() for candidate in candidates):
            raise  # Never bypass validation of an already accepted receipt.
        for candidate in candidates:
            if (candidate/'result.json').exists() or not (candidate/'worker.log').exists():
                continue
            log = (candidate/'worker.log').read_text(errors='replace')
            if ('ValueError: Animated/constrained native environment requires explicit baking: ' not in log
                    and 'ValueError: Tracked LIGHT target must be a pure camera-closure EMPTY:' not in log):
                continue
            request = dict(native=artifacts['scene.blend'], export=artifacts['scene.glb'], frame=1,
                active_camera=native['active_camera'], output=str(candidate), request_path=str(candidate/'request.json'))
            if read_json(candidate/'request.json') != request:
                raise ValueError('Failed environment dependency request changed')
            for pointer in (request['native'], request['export']):
                pin(pointer['path'], pointer['sha256'])
            target = folder.parent.with_name('export-environment-dependency')/folder.name
            return _exported_scene(artifacts, native, target,
                worker=ROOT/'src/evaluator/environment_dependency_export_blender.py')
        raise

def supported_exported_scene(artifacts, native, folder, *, worker=None, allow_tracked_camera=False):
    worker=worker or ROOT/'src/evaluator/continuous_image_export_blender.py'
    if not allow_tracked_camera or worker.name!='keyframed_camera_export_blender.py':
        return _exported_scene(artifacts,native,folder,worker=worker)
    if (folder/'result.json').exists():
        return _exported_scene(artifacts,native,folder,worker=worker)
    # A keyframed environment refusal can precede any camera refusal. Keep
    # these capability branches separate; the new worker rechecks LIGHT-only
    # actions and the original strict camera rules against the bound source.
    log=folder/'worker.log'
    animated_refusal=lambda:log.exists() and 'ValueError: Animated/constrained native environment requires explicit baking: ' in log.read_text(errors='replace')
    if animated_refusal():
        animated_folder=animated_light_fallback(artifacts,native,folder,worker)
        return _exported_scene(artifacts,native,animated_folder,worker=ROOT/'src/evaluator/animated_light_export_blender.py')
    tracked_folder=folder.parent.with_name('export-tracked')/folder.name
    if not (tracked_folder/'result.json').exists():
        try:return _exported_scene(artifacts,native,folder,worker=worker)
        except ValueError:
            # Eligibility below rejects every error except the pinned worker's
            # exact dependency capability refusal with unchanged source hashes.
            if animated_refusal():
                animated_folder=animated_light_fallback(artifacts,native,folder,worker)
                return _exported_scene(artifacts,native,animated_folder,worker=ROOT/'src/evaluator/animated_light_export_blender.py')
            tracked_camera_fallback(artifacts,native,folder,worker)
    tracked_folder=tracked_camera_fallback(artifacts,native,folder,worker)
    tracked_worker=ROOT/'src/evaluator/tracked_camera_export_blender.py'
    if (tracked_folder/'result.json').exists():
        return _exported_scene(artifacts,native,tracked_folder,worker=tracked_worker)
    light_folder=tracked_folder.parent.with_name('export-light-tracked')/tracked_folder.name
    if not (light_folder/'result.json').exists():
        try:return _exported_scene(artifacts,native,tracked_folder,worker=tracked_worker)
        except ValueError:light_tracked_fallback(artifacts,native,tracked_folder,tracked_worker)
    light_folder=light_tracked_fallback(artifacts,native,tracked_folder,tracked_worker)
    return _exported_scene(artifacts,native,light_folder,
                           worker=ROOT/'src/evaluator/light_tracked_camera_export_blender.py')

def _exported_scene(artifacts, native, folder, *, worker=None):
    worker = worker or ROOT/'src/evaluator/continuous_image_export_blender.py'
    request = {'native': artifacts['scene.blend'], 'export': artifacts['scene.glb'],
        'frame': 1, 'active_camera': native['active_camera'], 'output': str(folder),
        'request_path': str(folder/'request.json')}
    folder.mkdir(parents=True, exist_ok=True)
    if worker.name in {'tracked_camera_export_blender.py','light_tracked_camera_export_blender.py','animated_light_export_blender.py','environment_dependency_export_blender.py'}:
        folder.chmod(0o777);folder.parent.chmod(0o777)
    if not (folder/'result.json').exists():
        write_json(folder/'request.json', request)
        with (folder/'worker.log').open('w') as stream:
            result = subprocess.run([str(BLENDER), '-b', '--factory-startup', '--disable-autoexec',
                '--threads', '2', '--python-exit-code', '1', '--python', str(worker), '--', str(folder/'request.json')],
                stdout=stream, stderr=subprocess.STDOUT, timeout=900,
                env={**os.environ, 'OMP_NUM_THREADS':'2', 'OPENBLAS_NUM_THREADS':'2'})
        if result.returncode:
            raise ValueError('Export rendering environment failed: '+str(folder/'worker.log'))
    result = read_json(folder/'result.json')
    if worker.name == 'keyframed_camera_export_blender.py':
        from src.evaluator.keyframed_camera_export_blender import assert_same, BASE_SHA256
        validation = result['camera_action_validation']
        if (not validation['animation_preserved'] or validation['base_worker_sha256'] != BASE_SHA256
                or digest(worker.with_name('continuous_image_export_blender.py')) != BASE_SHA256):
            raise ValueError('Keyframed export validation changed')
        assert_same(validation['before'], validation['after'])
    if worker.name in {'tracked_camera_export_blender.py','light_tracked_camera_export_blender.py','animated_light_export_blender.py','environment_dependency_export_blender.py'}:
        from src.evaluator.tracked_camera_export_blender import assert_samples,BASE_SHA256,KEYFRAMED_SHA256
        validation=result['tracked_camera_validation']
        if (not validation['animation_preserved'] or not validation['constraints_preserved']
                or validation['maximum_absolute_tolerance']!=1e-6
                or validation['base_worker_sha256']!=BASE_SHA256
                or validation['keyframed_worker_sha256']!=KEYFRAMED_SHA256
                or digest(worker.with_name('continuous_image_export_blender.py'))!=BASE_SHA256
                or digest(worker.with_name('keyframed_camera_export_blender.py'))!=KEYFRAMED_SHA256
                or result.get('native_geometry_retained') is not False
                or validation['native_meshes_before_import']!=0 or not validation['imported_mesh_sha256']
                or validation['authored_before']!=validation['authored_after']):
            raise ValueError('Tracked camera export validation changed')
        assert_samples(validation['before'],validation['after'])
    if worker.name == 'environment_dependency_export_blender.py':
        from src.evaluator.environment_dependency_export_blender import TRACKED_SHA256, LIGHT_SHA256
        proof = result['environment_dependency_validation']
        if (proof['tracked_worker_sha256'] != TRACKED_SHA256
                or digest(worker.with_name('tracked_camera_export_blender.py')) != TRACKED_SHA256
                or proof['light_worker_sha256'] != LIGHT_SHA256
                or digest(worker.with_name('light_tracked_camera_export_blender.py')) != LIGHT_SHA256
                or not proof['lights'] or not proof['full_light_state_preserved']
                or proof['light_settings_before'] != proof['light_settings_after']
                or proof['animation_baked'] is not False
                or proof['constraint_targets'] != 'pure_empty_camera_or_light_dependency_closure'):
            raise ValueError('Environment dependency validation changed')
    if worker.name=='animated_light_export_blender.py':
        from src.evaluator.animated_light_export_blender import TRACKED_SHA256,LIGHT_STATE_SHA256
        lights=result['animated_light_validation']
        if (lights['tracked_worker_sha256']!=TRACKED_SHA256
                or digest(worker.with_name('tracked_camera_export_blender.py'))!=TRACKED_SHA256
                or lights['light_state_worker_sha256']!=LIGHT_STATE_SHA256
                or digest(worker.with_name('light_tracked_camera_export_blender.py'))!=LIGHT_STATE_SHA256
                or lights['base_worker_sha256']!=BASE_SHA256 or lights['keyframed_worker_sha256']!=KEYFRAMED_SHA256
                or not lights['lights'] or not lights['full_light_state_preserved']
                or not lights['nodes_and_socket_defaults_preserved'] or lights['animation_baked'] is not False
                or lights['constraint_policy']!='no_light_parent_constraints_drivers_nla'
                or lights['camera_policy']!='strict_keyframed'
                or lights['light_settings_before']!=lights['light_settings_after']):
            raise ValueError('Animated-light export validation changed')
    if worker.name=='light_tracked_camera_export_blender.py':
        from src.evaluator.light_tracked_camera_export_blender import TRACKED_SHA256
        lights=result['light_tracked_validation']
        if (lights['tracked_worker_sha256']!=TRACKED_SHA256
                or digest(worker.with_name('tracked_camera_export_blender.py'))!=TRACKED_SHA256
                or lights['base_worker_sha256']!=BASE_SHA256
                or lights['keyframed_worker_sha256']!=KEYFRAMED_SHA256
                or not lights['lights'] or not lights['full_light_state_preserved']
                or not lights['nodes_and_socket_defaults_preserved'] or lights['animation_baked'] is not False
                or lights['light_settings_before']!=lights['light_settings_after']
                or lights['constraint_targets']!='pure_empty_in_camera_dependency_closure'):
            raise ValueError('Light-tracked export validation changed')
    if read_json(folder/'request.json') != request or result['request_sha256'] != digest(folder/'request.json') or result['worker_sha256'] != digest(worker):
        raise ValueError('Export context binding changed')
    return pin(**{'path':result['scene']['path'], 'expected':result['scene']['sha256']})

def artifact_variants(run_dir, run, l1):
    result = {}
    record = read_json(run_dir/'execution_record.json')
    hashes = record.get('artifact_sha256', {})
    result['primary'] = {name:pin(run_dir/'submission'/name, sha) for name,sha in hashes.items()
                         if name in {'scene.blend','scene.glb','main.png','alternate.png','novel.png'}}
    for seed in run['seeds']:
        attempts = run['attempts'].get('seed-'+str(seed), [])
        if not attempts or attempts[-1].get('status') != 'success':
            raise ValueError('Required seed execution unavailable')
        last = attempts[-1]
        result['seed-'+str(seed)] = {name:pin(Path(last['workspace'])/'output'/name, sha)
            for name,sha in last['artifact_sha256'].items()
            if name in {'scene.blend','scene.glb','main.png','alternate.png','novel.png'}}
    return result

def evaluate(root, model, row):
    folder = root/'linear_results'/model/Path(row['task_id']).name
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'case.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return _evaluate(root, model, row, folder)

def _evaluate(root, model, row, folder):
    policy = read_json(checked(read_json(root/'linear_policy.sha256.json')))
    rule = read_json(checked(policy['rules'][row['task_id']]))
    for name, sha in policy['files'].items():
        if name.startswith('linear_config/'+row['task_id']+'/') and digest(root/name) != sha:
            raise ValueError('Frozen task rule changed')
    campaign = read_json(root/'campaign.json')
    task = Path(campaign['frozen'])/'data/3dbench/tasks'/row['task_id']
    run_dir = Path(row['run_dir']); run = read_json(run_dir/'run.json')
    if run.get('model_call') is not True or run['task_id'] != row['task_id']:
        raise ValueError('Fresh model generation required')
    generation = read_json(run_dir/'generation.json')
    if any(a['model'] != model for a in generation['attempts']):
        raise ValueError('Generator model differs')
    old = read_json(Path(run['report_path'])) if run.get('report_path') else {}
    base = {'task_id':row['task_id'], 'model':model, 'category':rule['category'], 'level':rule['level'],
        'release_id':VERSION, 'batch_id':root.name, 'profile':VERSION+'/'+rule['category'],
        'source_run':pin(run_dir/'run.json'), 'generation':pin(run_dir/'generation.json'),
        'source_report':pin(run['report_path']) if run.get('report_path') else None,
        'spec_sha256':row['spec_sha256'], 'instruction_sha256':digest(task/'instruction.md'),
        'case_policy_sha256':row.get('case_policy_sha256'), 'policy_sha256':digest(root/'linear_policy.json'),
        'implementation':implementation_binding(root),
        'formal_score_eligible':False, 'updated_utc':now()}
    if (folder/'report.json').exists():
        saved = read_json(folder/'report.json')
        if saved['source_run'] != base['source_run'] or saved['policy_sha256'] != base['policy_sha256']:
            raise ValueError('Previously evaluated candidate changed')
        if saved['S_core'] is not None:
            return saved
    atomic(folder/'status.json', {**base, 'status':'evaluating'})
    valid = None
    if rule['level'] == 'L1' and old and (run_dir/'execution_record.json').exists():
        gates = system_gates(run_dir, run, old, read_json(run_dir/'execution_record.json'), {})
        states = [g['measurement_status'] for g in gates.values()]
        valid = False if 'failed' in states else True if all(s=='passed' for s in states) else None
        if rule['category']=='CodeEdit':
            valid = old.get('score_valid') if classify(run,generation,old)=='scored' else None
    elif old:
        # The legacy report also sets score_valid=false for evaluator failures.
        # Only a completed numerical report can establish a candidate failure.
        valid = True if old.get('score_valid') is True else old.get('score_valid') if classify(run,generation,old)=='scored' else None
    if classify(run, generation, old) == 'model_failure':
        valid = False
    if not (run_dir/'submission/scene.blend').exists():
        if valid is not False:
            raise ValueError('No valid executed native candidate; '+str(run.get('error')))
    keys = rule['weights']
    original = {k:old.get('score_components',{}).get(k) for k in keys}
    if valid is False or rule['category']=='CodeEdit':
        result = {**base, **aggregate(rule['category'],rule['level'],original,keys,
            detail=None,vlm=None,valid=valid), 'valid':valid, 'measurements':[],
            'status':'system_invalid' if valid is False else 'scored' if valid is True else 'not_measurable',
            'judgments':{}, 'images':{}}
        atomic(folder/'report.json', result)
        return result
    if rule['category']=='Text2Code':
        plan = read_json(root/'linear_config'/row['task_id']/'alignment.json')
        original['data'] = measure_data(plan, flatten(old))['score']
    config = replace(JudgeConfig.from_env(env_path()), model=judge_model(), effort='medium',
                     timeout=600, attempts=3, base_url=campaign['provider_transport'])
    if (root/'evaluation_runtime.json').exists():
        runtime = read_json(root/'evaluation_runtime.json')
        pin(runtime['codex'],runtime['codex_sha256'])
        config = replace(config,codex=runtime['codex'],
                         base_url=runtime.get('provider_transport',config.base_url))
    variants = artifact_variants(run_dir, run, rule['level']=='L1')
    views = {}
    if (root/'view_policy.sha256.json').exists():
        views = read_json(checked(read_json(root/'view_policy.sha256.json')))['tasks']
    groups = {}; judgments = {}; provenance = {}; automatic = {'main_image':{},'localization':{}}
    evidence = {}; reused = {}
    for variant in rule['variants']:
        seed, fmt = variant.split('/') if '/' in variant else (variant,'native')
        exported = fmt=='glb'; name = 'export' if exported else 'native'
        spec = read_json(checked(rule['specs'][name])); groups[variant] = rule['groups'][name]
        current = variants[seed]; dest = folder/'variants'/variant
        if rule['level']=='L1':
            native = collect_native(Path(current['scene.blend']['path']),folder/'native'/seed,1,
                studio=rule['category']=='Text2Code',main_required=True)
            scene = exported_scene(current,native,folder/'export'/seed) if exported else current['scene.blend']
            rendered = collect_native(Path(scene['path']),dest/'render',1,studio=False,main_required=True) if exported else native
            artifacts = {'scene.blend':scene, **{k+'.png':{f:v[f] for f in ('path','sha256')} for k,v in rendered['renders'].items()}}
            if row['task_id'] in views:
                requested = [{**v,'image':str(dest/'paired'/v['id'])} for v in views[row['task_id']]['views']]
                paired = render(scene,requested,dest/'paired')
                artifacts.update({k:v['image'] for k,v in paired['views'].items()})
        else:
            artifacts = dict(current)
        evidence[variant] = artifacts
        # Equality of the complete native file and both image bytes is sufficient for exact reuse.
        signature = tuple([rule['specs'][name]['sha256'], *[artifacts[k]['sha256'] for k in ('scene.blend','main.png','alternate.png')]])
        if signature in reused:
            source = reused[signature]
            judgments[variant] = judgments[source]; provenance[variant] = provenance[source]
            for key in automatic:
                if source in automatic[key]:automatic[key][variant] = automatic[key][source]
            continue
        plan = {'_vlm_judge':{'version':'continuous-task-judge-v1','spec':spec,
            'spec_sha256':rule['specs'][name]['sha256'],'mode':'interactive','edit_context':rule['edit_context']}}
        archive_preflight_failure(dest/'judge')
        observations = judge_task(task, {'artifacts':artifacts,'reference_images':rule['reference_images']},
            plan,dest/'judge',config=config,tested_model=model,blender=BLENDER)
        judgments[variant] = observations if observations.get('status')=='scored' else None
        provenance[variant] = pin(dest/'judge/run.json')
        reused[signature] = variant
        if rule['category'].startswith(('Image2Code','Reference2Scene')) and not exported:
            locfile = root/'linear_config'/row['task_id']/'localization.json'
            locspec = read_json(locfile)
            archive_preflight_failure(dest/'localization')
            loc = judge_task(task, {'artifacts':artifacts,'reference_images':rule['reference_images']},
                {'_vlm_judge':{'version':'l2-vlm-judge-v2','spec':locspec,'spec_sha256':digest(locfile),'mode':'interactive'}},
                dest/'localization',config=config,tested_model=model,blender=BLENDER)
            automatic['localization'][variant] = loc.get('localization',{}).get('score') if loc.get('status')=='scored' else None
            if rule['level']=='L1':
                reference = next(p for p in rule['reference_images'].values() if p['sha256']==locspec['localization']['reference_sha256'])
                a,b = [np.asarray(Image.open(p['path']).convert('RGB'),dtype=float)/255 for p in (reference,artifacts['main.png'])]
                region = root/'linear_config'/row['task_id']/'reference_regions.json'
                measurement = regional_components(a,b,read_json(region)) if region.exists() else appearance_components(a,b)
                automatic['main_image'][variant] = measurement['score']
                write_json(dest/'appearance.json', {'reference':reference,'candidate':artifacts['main.png'],**measurement})
            # L2 retains its existing independently measured static regions and
            # dual-view weights, including the final all-seed minimum.
        atomic(folder/'status.json', {**base,'status':'evaluating','variants_finished':len(judgments),'variants_total':len(rule['variants'])})
    native_values = {}
    for atom in rule['native_atoms']:
        path = folder/(atom['id']+'.json')
        values = read_json(path)['values'] if path.exists() else {}
        native_values['detail_'+atom['id']] = {'weight':atom['weight'],'values':values}
    minimum, selected, values = variant_components(groups,judgments,native_values)
    for key,population in automatic.items():
        if population:
            original[key] = min(population.values()) if all(v is not None for v in population.values()) else None
    output = aggregate(rule['category'],rule['level'],original,keys,valid=valid,**minimum)
    measurements = []
    for key, variant in selected.items():
        if not variant or key=='content':continue
        weights = dict(groups[variant][key]); raw = judgments[variant]['criterion_scores']
        observations = {c['check_id']:c for c in judgments[variant]['criteria']}
        if key=='detail':
            raw = dict(raw)
            for k,v in native_values.items():weights[k]=v['weight'];raw[k]=v['values'][variant]['value']
        for k,w in weights.items():
            weight = output['component_weights'][key]*w/sum(weights.values())
            measurements.append({'id':k,'component':key,'value':raw[k],'weight':w/sum(weights.values()),
                'global_weight':weight,'contribution_points':100*weight*raw[k],
                'selected_variant':variant,'observation':observations.get(k),
                'definition':{'question':k,'measurement_rule':'覆盖率 × (1−偏差)；原生项保留实测'},
                'raw_source':provenance[variant],'raw_field':'criterion_scores/'+k})
    result = {**base,**output,'valid':valid,'status':'scored' if output['S_core'] is not None else 'not_measurable',
        'judgments':provenance,'images':evidence.get('primary/native',evidence.get('primary',{})),
        'component_variants':selected,'component_values_by_variant':values,'automatic_by_variant':automatic,
        'measurements':measurements,'native_detail_values':native_values}
    atomic(folder/'report.json',result)
    return result
