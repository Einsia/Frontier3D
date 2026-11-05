"""Evidence-based diagnostics. Missing evidence never becomes a passing score."""
from __future__ import annotations
import math, statistics
from pathlib import Path
from .protocol import *
from harness.L3.scoring import metric_template, rubric_results


def entity(frame, key):
    matches=[e for e in frame.get('entities',[]) if e.get('id')==key]
    if len(matches)!=1: raise ValueError(f'Entity must occur exactly once: {key}')
    return matches[0]


def meshes(e):
    return [c for c in e.get('components',[]) if c.get('mesh') and c.get('instances',0)>0 and c.get('visible')]


def signature(e):
    return [(c['name'],c.get('mesh'),c.get('instances'),c.get('visible'),c.get('collision'),
             c.get('position_cm'),c.get('rotation_deg'),c.get('bounds_extent_cm'))
            for c in sorted(e.get('components',[]),key=lambda c:c['name'])]


def changed(a,b): return signature(a)!=signature(b)


def movement(a,b):
    before={c['name']:c for c in meshes(a)}
    rotation=distance=0.
    for c in meshes(b):
        if c['name'] not in before: continue
        old=before[c['name']]
        rotation=max(rotation,max(abs((x-y+180)%360-180) for x,y in zip(c['rotation_deg'],old['rotation_deg'])))
        distance=max(distance,math.dist(c['position_cm'],old['position_cm']))
    return rotation,distance


def local_diagnostics(folder: Path, plan: dict, binding: dict):
    if not read_json(folder/'completed.json').get('completed'): raise ValueError('episode did not complete')
    target=plan['target']
    def frame(name):
        f=read_json(folder/(name+'.json'))
        if f.get('protocol')!='ue5-observer-v1': raise ValueError('unknown observation protocol')
        return f
    def ent(name): return entity(frame(name),target)
    def event(name): return read_json(folder/(name+'_event.json'))
    before,after=ent('before'),ent('after_1')
    checks={'real_geometry':bool(meshes(before)),
            'negative_call_reached_candidate':event('far_action').get('dispatched',False),
            'far_geometry_unchanged':not changed(ent('far_before'),ent('far_after'))}
    diagnostics={}
    if target in DOORS:
        after2,after3=ent('after_2'),ent('after_3')
        checks.update(action_path_accepted=all(event(f'action_{i}')['accepted'] for i in [1,2,3]),
                      leaf_rotates=60<=movement(before,after)[0]<=120,
                      leaf_remains_visible=bool(meshes(after)) and bool(meshes(after2)) and bool(meshes(after3)),
                      closes_again=movement(before,after2)[0]<=2 and movement(before,after2)[1]<=2,
                      closed_barrier=event('closed_probe')['blocked'] and event('closed_probe')['hit']==target,
                      opened_passage=not event('probe_1')['blocked'] and not event('probe_3')['blocked'],
                      closed_again=event('probe_2')['blocked'] and event('probe_2')['hit']==target,
                      actual_walk_through=math.dist(frame('crossed')['pawn_position_cm'],binding['crossing_to_cm'])<80)
        # Candidate coordinates are hints. A floor/wall hit cannot establish
        # the intended door barrier or passage, so preserve an unresolved check.
        if not checks['closed_barrier']:
            diagnostics['probe_validation']={'status':'pending_fixture_calibration',
                'closed_probe_hit':event('closed_probe').get('hit'),
                'reason':'Closed probe must hit the target door before open/close results are interpretable.'}
            for key in ('closed_barrier','opened_passage','closed_again'): checks[key]=None
        samples=[read_json(p) for p in sorted(folder.glob('trajectory_*.json'))]
        moving=[entity(f,target) for f in samples if f.get('active_step') in {'wait_1','motion_wait_1','motion_view_1'}]
        intermediates=[e for e in moving if 3<movement(before,e)[0]<57]
        checks['sampled_intermediate_motion']=len(intermediates)>=2
        baseline={(c['name'],x['actor'],x['component']) for c in before['components'] for x in c.get('blocking_contacts',[])}
        contacts={(c['name'],x['actor'],x['component']) for e in moving for c in e['components'] for x in c.get('blocking_contacts',[])}
        diagnostics['new_blocking_contacts']=sorted(contacts-baseline)
        diagnostics['contact_interpretation']='Collision-shape overlap at sampled poses; inspect animation frames. Contact is not penetration depth, and absence is not a continuous collision proof.'
    elif target in CHESTS:
        checks.update(action_path_accepted=event('action_1')['accepted'],
                      visible_lid_motion=movement(before,after)[0]>=30 or movement(before,after)[1]>=15,
                      repeat_take_no_geometry_duplication=not changed(ent('after_2'),ent('after_3')))
    elif target in CROPS:
        checks.update(harvest_accepted=event('action_1')['accepted'],
                      harvest_changes_geometry=changed(before,after),
                      repeat_harvest_does_not_change_geometry=not changed(after,ent('after_2')))
        diagnostics['planting_requires_seeds']='Evaluated in the inventory-bearing E2E episode; a fresh local episode has no chest seeds.'
    elif target in BLOCKS:
        visible_solid=lambda e: sum(c.get('instances',1) for c in meshes(e) if c.get('collision') and c.get('blocks_pawn'))
        checks.update(remove_accepted=event('action_1')['accepted'],
                      removes_visible_collision=visible_solid(after)<visible_solid(before),
                      repeated_remove_stable=not changed(after,ent('after_2')),
                      restores_visible_collision=visible_solid(ent('after_3'))==visible_solid(before) and bool(meshes(ent('after_3'))))
    else:
        checks['empty_furnace_does_not_change_geometry']=not changed(before,after)
        diagnostics['processing_requires_crop']='Actual lit processing and item conservation require the E2E episode; candidate semantic strings alone never pass these checks.'
    return {'target':target,'checks':checks,'automatic_fraction':sum(v is True for v in checks.values())/len(checks),
            'check_counts':{'passed':sum(v is True for v in checks.values()),
                            'failed':sum(v is False for v in checks.values()),
                            'unresolved':sum(v is None for v in checks.values()),'total':len(checks)},
            'diagnostics':diagnostics,'semantic_state_used_for_score':False}


def journey_diagnostics(folder):
    initial=read_json(folder/'initial.json')
    frames=[initial]+[read_json(p) for p in sorted(folder.glob('trajectory_*.json'))]+[read_json(folder/'final.json')]
    points=[f['pawn_position_cm'] for f in frames]
    travelled=sum(math.dist(a,b) for a,b in zip(points,points[1:]))
    span=max(math.dist(points[0],p) for p in points)
    max_jump=max((math.dist(a['pawn_position_cm'],b['pawn_position_cm'])/max(.0001,b['time']-a['time'])
                  for a,b in zip(frames,frames[1:]) if b['time']>a['time']),default=0)
    ok=travelled>=2500 and span>=1200 and max_jump<1200 and all(p[2]>-2000 for p in points)
    return dict(travelled_cm=travelled,span_cm=span,max_observed_speed_cm_s=max_jump,passed=ok,
                limitation='Movement coverage diagnostic; landmark visits and unobstructed layout need visual review.')


def summarize(run: Path):
    manifest=read_json(run/'run.json')
    if manifest.get('status')!='executed':
        return {**metric_template('image'), 'status':manifest.get('status','invalid'),
                'reason':manifest.get('reason')}
    if manifest.get('source_sha256')!=tree_digest(Path(manifest['project'])):
        raise ValueError('Project source changed after execution')
    for relative,expected in manifest['evidence_sha256'].items():
        p=run/relative
        if p.is_symlink() or not p.resolve().is_relative_to(run.resolve()) or digest(p)!=expected: raise ValueError('Evidence changed: '+relative)
    actual={str(p.relative_to(run)) for area in ['episodes','plans'] for p in (run/area).rglob('*') if p.is_file()}
    expected={x for x in manifest['evidence_sha256'] if x.startswith(('episodes/','plans/'))}
    if actual!=expected: raise ValueError('Evidence file set changed after execution')
    bindings=read_json(run/'bindings.json'); episodes={}
    for target in REQUIRED:
        name=target.replace('.','_'); plan=read_json(run/'plans'/(name+'.json'))
        episodes[target]=local_diagnostics(run/'episodes'/name,plan,bindings['entities'][target])
    groups=[DOORS,CHESTS,CROPS,BLOCKS,FURNACES]
    auto=statistics.mean(statistics.mean(episodes[t]['automatic_fraction'] for t in group) for group in groups)
    initial=read_json(run/'episodes/views/initial.json')
    ids=[e['id'] for e in initial['entities']]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate entity IDs')
    component_ratio=sum(bool(meshes(entity(initial,t))) if t in ids else False for t in BUILDINGS+REQUIRED)/len(BUILDINGS+REQUIRED)
    journey=journey_diagnostics(run/'episodes/journey')
    report={'status':'partial_evidence','score':None,'calibration':'pilot; not a validated leaderboard metric',
            'episodes':episodes,'automatic_function_diagnostics':auto,'component_presence':component_ratio,
            'journey':journey,'pending':['independent_visual_judging','curated_continuous_workflow','human_calibration'],
            'note':'Presence counts do not establish correct appearance, scale, interior detail or semantic inventory correctness.'}
    visual=run/'visual.json'
    if visual.exists():
        v=read_json(visual)
        if v.get('run_manifest_sha256')!=digest(run/'run.json'): raise ValueError('VLM evidence belongs to another run')
        report['visual']=v
        report['pending'].remove('independent_visual_judging')
    if manifest.get('e2e_included'):
        flow=e2e_diagnostics(run);report['e2e']=flow
        report['pending'].remove('curated_continuous_workflow')
    report.update(aggregate(report,report.get('visual',{}),report.get('e2e',{})))
    return report


def e2e_diagnostics(run: Path):
    plan=validate_plan(read_json(run/'plans/e2e.json'))
    if plan['kind']!='e2e': raise ValueError('Expected continuous workflow')
    folder=run/'episodes/e2e'
    required=[('house01.chest','take'),('farm.crop01','harvest'),('farm.crop01','plant'),('smithy01.furnace','process'),('storehouse.chest','take')]
    actions=[s for s in plan['steps'] if s['op']=='interact']
    seen=[(s['target'],s['action']) for s in actions]
    if any(x not in seen for x in required):raise ValueError('E2E plan omits required workflow actions')
    if not all(seen.index(a)<seen.index(b) for a,b in zip(required,required[1:])):raise ValueError('Workflow order is invalid')
    captures={s['name'] for s in plan['steps'] if s['op']=='capture'}
    if not {'seed_acquired','crop_replanted','furnace_active','processed','storage_visited','returned_storage'} <= captures:
        raise ValueError('E2E needs required visual checkpoints')
    frames=[read_json(folder/'initial.json')]+[read_json(p) for p in sorted(folder.glob('trajectory_*.json'))]+[read_json(folder/'final.json')]
    first,last=frames[0],frames[-1]
    checks={f'{target}:{action}':any(read_json(folder/(s['name']+'_event.json')).get('accepted') for s in actions if (s['target'],s['action'])==(target,action)) for target,action in required}
    checks['walks_across_region']=journey_diagnostics(folder)['passed']
    checks['crop_world_effect']=changed(entity(first,'farm.crop01'),entity(last,'farm.crop01'))
    lights=[]
    for f in frames:
        e=entity(f,'smithy01.furnace')
        lights.append(sum(l['intensity'] for l in e.get('lights',[]) if l['visible']))
    # Emissive-material furnaces can be verified in rendered images instead of lights.
    return {'checks':checks,'automatic_pass':all(checks.values()),
            'route_validated':plan.get('curation_status')=='human_traversal_verified',
            'curation_status':plan.get('curation_status','unverified'),'furnace_light_change':max(lights,default=0)>min(lights,default=0),
            'inventory_verification':'Requires visual checkpoints; candidate state strings are not an independent ledger.'}


def aggregate(report, visual, e2e):
    """Report measurements and judgments without manufacturing an aggregate score."""
    result=metric_template('image')
    result['rubrics']=rubric_results(visual)
    result['status']='partial_evidence'
    result['deterministic']['layout']['diagnostics']={'journey':report.get('journey')}
    result['deterministic']['interaction'].update(
        mechanism_diagnostics={name:{'checks':item['checks'],
                                     'check_fraction':item['automatic_fraction'],
                                     'check_counts':item.get('check_counts'),
                                     'diagnostics':item.get('diagnostics',{})}
                               for name,item in report.get('episodes',{}).items()},
        continuous_workflow_diagnostics=e2e or None,
        limitation='Runtime checks need engine validation and an independent inventory oracle; VLM review does not supply deterministic success.')
    result['core_workflow_completed']=None
    # A known failure is conclusive; incomplete checks or a positive VLM verdict
    # cannot certify an unseen inventory transaction or the whole workflow.
    known_failure=any(any(v is False for v in item['checks'].values()) for item in report.get('episodes',{}).values())
    if known_failure or (e2e.get('route_validated') is True and e2e.get('automatic_pass') is False):
        result['core_workflow_completed']=False
    result['calibration']='Pilot diagnostics; calibrated geometry, reference annotations and inventory observations pending.'
    return result
