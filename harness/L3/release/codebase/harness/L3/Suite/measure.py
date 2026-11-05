"""Algorithmic layout and function measurements over independent runtime evidence."""
from collections import defaultdict
import json,math,os,time,threading
import numpy as np
from .policy import read,write,POLICY,OUT
from .observations import entities,parts,pos,changed,physical_effect,inventory,goals,negative_unchanged
from harness.L3.MinecraftVillage.algorithm_geometry import compact
from harness.L3.MinecraftVillage.scene_geometry import Scene,broad_pairs,instance_key,motion_measure
from harness.L3.MinecraftVillage.support import measure as support_measure
from harness.L3.MinecraftVillage.physical_scene import physical_scene
from harness.L3.MinecraftVillage.algorithm_scores import blend,rigid_coverage
SUPPORT_LOCK=threading.Lock()
def mean(xs):
 xs=list(xs);return sum(xs)/len(xs) if xs and all(x is not None for x in xs) else None
def macro(rows,roles):
 groups=defaultdict(list)
 for id,value in rows.items():groups[roles.get(id,'scene_static')].append(value)
 scores={k:mean(v) for k,v in groups.items()}
 return {'score':mean(scores.values()),'groups':scores,'entities':rows}
def read_frame(folder,name):
 p=folder/(name+'.json')
 if not p.exists():raise RuntimeError('Missing independent observation '+str(p))
 f=read(p)
 if f.get('protocol')!='ue5-observer-v1':raise RuntimeError('Wrong observer protocol')
 return f
def observations(folder):
 from .crash_recovery import checked_crashes
 crashes=checked_crashes(folder)
 contract=read(folder/'contract.json');roles={e['id']:e['role'] for e in contract['entities']};required=list(roles)
 work=folder/'workspace/episodes/workflow';local=folder/'workspace/episodes/local'
 wm=read(folder/'workflow-metadata.json');lm=read(folder/'local-metadata.json')
 if not read(work/'completed.json').get('completed'):raise RuntimeError('Incomplete independent workflow episode')
 initial=read_frame(work,'initial');final=read_frame(work,'final')
 frames=[initial];positive={id:False for id in required};walks=[];physical_calls=[]
 for row in wm['steps']:
  a=read_frame(work,row['before']);b=read_frame(work,row['after']);frames.extend([a,b]);step=row['step']
  for id in required:
   if physical_effect(a,b,id,required):positive[id]=True
  if step['op']=='walk_to':
   distance=float(np.linalg.norm(np.array(b.get('pawn_position_cm',[math.inf]*3))-np.array(step['target_cm'])))
   walks.append({'name':step['name'],'distance_cm':distance if math.isfinite(distance) else None,'passed':distance<=POLICY['navigation_tolerance_cm']})
  if step['op'] in {'interact','invoke'}:
   physical_calls.append({'name':step['name'],'target':step['target'],'action':step['action'],'target_physical_effect':physical_effect(a,b,step['target'],required),
     'inventory_changed':inventory(a)!=inventory(b)})
 frames.append(final)
 local_rows={};door_walk=[];constraints={}
 for row in lm.get('constraints',[]):
  name=row['name'];a=read_frame(local,name+'_before');b=read_frame(local,name+'_after')
  passed=name not in crashes and negative_unchanged(read_frame(local,name+'_control'),a,b,row['id'])
  constraints.setdefault(row['id'],[]).append({**row,'passed':passed,'candidate_crash':name in crashes})
 for row in lm['entities']:
  id=row['id'];present=len([e for e in initial['entities'] if e['id']==id])==1 and bool(parts(initial,id))
  if row.get('binding_missing'):
   local_rows[id]={'score':0.,'status':'missing_required_public_binding','presence':float(present)};continue
  pre=row['prefix'];negative=None
  if row['actions']:
   a=read_frame(local,pre+'_neg_before');b=read_frame(local,pre+'_neg_after')
   negative=float(pre+'_neg' not in crashes and negative_unchanged(read_frame(local,pre+'_control_before'),a,b,id))
  else:negative=1.
  effects=[]
  for action in row['positive']:
   a=read_frame(local,action['name']+'_before');b=read_frame(local,action['name']+'_after')
   effect=physical_effect(a,b,id,required)
   if roles[id] in {'key','keycard'}:effect=effect or inventory(a)!=inventory(b)
   if action['name'] in crashes:effect=False
   positive[id]=positive[id] or effect;effects.append({'action':action['action'],'physical_effect':bool(effect),'candidate_crash':action['name'] in crashes})
  if 'walk_target' in row:
   f=read_frame(local,pre+'_walk_after');distance=float(np.linalg.norm(np.array(f.get('pawn_position_cm',[math.inf]*3))-row['walk_target']))
   door_walk.append({'target':id,'distance_cm':distance if math.isfinite(distance) else None,'passed':distance<=POLICY['navigation_tolerance_cm']})
  invalid=row.get('invalid_probe')
  invalid_ok=invalid not in crashes and negative_unchanged(read_frame(local,invalid+'_control'),read_frame(local,invalid+'_before'),read_frame(local,invalid+'_after'),id) if invalid else None
  negative_checks=[negative]+([float(invalid_ok)] if invalid_ok is not None else [])+[float(x['passed']) for x in constraints.get(id,[])]
  negative=mean(negative_checks)
  if not present:negative=0.;positive[id]=False
  values={'presence':float(present),'positive_physical_effect':float(positive[id]),'invalid_reach_rejected':negative}
  local_rows[id]={**blend(values,POLICY['local_weights']),'checks':values,'actions':effects,'invalid_action_rejected':invalid_ok,'prerequisites':constraints.get(id,[])}
 local_macro=macro({id:v['score'] for id,v in local_rows.items()},roles)
 bindings=read(folder/'workspace/project/bindings.json')
 goal_rows=goals(folder.name,initial,final,frames,bindings)
 resource=mean(float(x['passed']) for x in goal_rows)
 route=mean(float(x['passed']) for x in walks) if walks else 0.0
 flow=bool(goal_rows and all(x['passed'] for x in goal_rows) and walks and all(x['passed'] for x in walks) and not wm['rejected'])
 result={'local':local_macro,'targets':local_rows,'physical_calls':physical_calls,'goals':goal_rows,'resource_state':resource,
  'navigation_evidence_status':'observed_walks' if walks else 'completed_episode_without_executable_walk',
  'continuous_workflow':float(flow),'route_success_fraction':route,'walks':walks,'door_walks':door_walk,
  'navigation':mean([route,mean(float(x['passed']) for x in door_walk)]) if door_walk else route,
  'state_and_workflow':.5*resource+.5*float(flow),'rejected_route_steps':wm['rejected'],
  'candidate_crashes':crashes,
  'scope':'Physical observations, real item geometry, actual pawn travel and trusted inventory; no semantic state strings or API success flags establish correctness.'}
 write(folder/'interaction-observations.json',result)
 return result
def geometry(folder):
 contract=read(folder/'contract.json');roles={e['id']:e['role'] for e in contract['entities']}
 source=folder/'workspace/episodes/views/scene_geometry.json'
 supplemental=folder/'geometry-supplement/result.json'
 if supplemental.exists():
  from pathlib import Path
  from harness.L3.MinecraftVillage.protocol import digest
  supplement=read(supplemental);source=Path(supplement['geometry'])
  assert supplement['status']=='collected' and digest(source)==supplement['sha256']
  assert supplement['source_sha256']==read(folder/'source.json')['source_sha256']
 export=read(source)
 physical,audit=physical_scene(export,__import__('pathlib').Path(read(folder/'source.json')['trial']))
 # Sky is a renderer background: only enormous noncolliding sphere shells.
 keep=[];background=[]
 for item in physical['instances']:
  axes=np.array([item['axis_x'],item['axis_y'],item['axis_z']])
  verts=np.array(physical['meshes'][item['mesh']]['vertices_cm'])@axes+item['origin_cm']
  if not item.get('collision_enabled') and 'Sphere.Sphere' in item['mesh'] and min(np.ptp(verts,axis=0))>=100000:
   background.append({'actor':item['actor'],'component':item['component'],'reason':'noncolliding sphere background with all diameters >= 1 km'});continue
  if roles.get(item['actor'])=='water':
   background.append({'actor':item['actor'],'component':item['component'],'reason':'public fluid entity excluded from rigid penetration; water motion tested separately'});continue
  keep.append(item)
 physical['instances']=keep
 physical,proof=compact(physical,protected_entities=set(roles))
 write(folder/'physical-scene.json',physical);write(folder/'geometry-exclusions.json',{'source_geometry':str(source),'organizer':audit,'background_and_fluid':background,'compaction':proof})
 scene=Scene(physical,open_surface_fallback=True);bad=set();overlaps=[];unresolved=[];checked=0;assembly_skipped=0
 for i,j in broad_pairs(scene.bounds):
  a,b=scene.items[i],scene.items[j]
  if a['actor']==b['actor'] and a['actor'] not in roles:assembly_skipped+=1;continue
  if np.any(np.minimum(scene.bounds[i,1],scene.bounds[j,1])-np.maximum(scene.bounds[i,0],scene.bounds[j,0])<=1e-6):continue
  checked+=1;res=scene.overlap(i,j,2.)
  record={'left':list(instance_key(a)),'right':list(instance_key(b)),**res}
  if res['violates'] is None:unresolved.append(record)
  elif res['violates']:overlaps.append(record);bad.update([a['actor'],b['actor']])
 stat={'measurement_complete':not unresolved,'unresolved_pair_count':len(unresolved),'unexported_components':physical.get('unexported_components',[]),
       'narrow_phase_pairs':checked,'overlaps':overlaps,'unresolved':unresolved,'assembly_internal_pairs_omitted':assembly_skipped}
 collision_only=[x for x in stat['unexported_components'] if x.get('class') in {'BoxComponent','SphereComponent','CapsuleComponent'}]
 coverage=rigid_coverage({**stat,'unexported_components':[x for x in stat['unexported_components'] if x not in collision_only]})
 coverage['collision_only_components']=collision_only
 coverage['collision_only_scope']='Analytical non-rendering shapes; actual blocking exercised by independent pawn travel. No missing render mesh.'
 stat['coverage']=coverage
 penetration=macro({id:float(id not in bad) for id in {i['actor'] for i in scene.items}},roles)
 if not coverage['exported_solids_complete']:penetration['score']=None
 write(folder/'static-geometry.json',{'raw':stat,'score':penetration})
 review_path=folder/'reviewed-ground.json';review=read(review_path) if review_path.exists() else None
 if review:
  from harness.L3.MinecraftVillage.protocol import digest
  if review['geometry_sha256']!=digest(folder/'physical-scene.json'):raise ValueError('Reviewed ground geometry changed')
 with SUPPORT_LOCK:support=support_measure(physical,maximum_triangles=100_000_000,maximum_pieces=1_000_000,maximum_triangle_pairs=500_000_000,reviewed_ground=review)
 support_macro=macro({x['actor']:1-x['unsupported_piece_count']/max(1,x['connected_piece_count']) for x in support['actors']},roles)
 if support['raw_l2'].get('status')!='measured':support_macro['score']=None
 write(folder/'support-geometry.json',{'raw':support,'score':support_macro})
 # Reuse the MC exact moving-mesh measurement with per-entity evidence slices.
 slices=folder/'motion-episodes';slices.mkdir(exist_ok=True)
 lm=read(folder/'local-metadata.json');prefixes={r.get('prefix'):r['id'] for r in lm['entities'] if r.get('prefix')}
 targets=[e['id'] for e in contract['entities'] if e['role'] not in {'receptacle','key','keycard','scanner','terminal','appliance','scale','water','pressure_plate'}]
 for id in targets:
  dest=slices/id.replace('.','_');dest.mkdir(exist_ok=True)
  init=dest/'initial.json'
  if not init.exists():os.link(folder/'workspace/episodes/local/initial.json',init)
 for path in sorted((folder/'workspace/episodes/local').glob('trajectory_*.json')):
  frame=read(path);active=frame.get('active_step','');prefix=active.split('_')[0];id=prefixes.get(prefix)
  if id not in targets or '_a' not in active:continue
  dest=slices/id.replace('.','_')/path.name
  if not dest.exists():os.link(path,dest)
 # Include actual workflow poses (lifts, floats and loaded transports) once per changed pose.
 baseline=read_frame(folder/'workspace/episodes/workflow','initial')
 previous={id:baseline for id in targets}
 for path in sorted((folder/'workspace/episodes/workflow').glob('trajectory_*.json')):
  frame=read(path)
  for id in targets:
   if not changed(previous[id],frame,id):continue
   dest=slices/id.replace('.','_')/('trajectory_w_'+path.stem+'.json')
   if not dest.exists():os.link(path,dest)
   previous[id]=frame
 for id in targets:
  dest=slices/id.replace('.','_')/'trajectory_w_zz_final.json'
  if not dest.exists():os.link(folder/'workspace/episodes/workflow/final.json',dest)
 motion={'method':'all_required_moving_parts_sampled_solids_v1','targets':{},'total_targets':len(targets)}
 checkpoints=folder/'motion-targets';checkpoints.mkdir(exist_ok=True)
 for id in targets:
  checkpoint=checkpoints/(id+'.json')
  if checkpoint.exists():row=read(checkpoint)
  else:
   detail=motion_measure(scene,slices,targets=[id],stop_on_failure=True);row=detail['targets'][id]
   write(checkpoint,row)
  motion['targets'][id]=row
  write(folder/'physical-progress.json',{'stage':'motion','completed_targets':len(motion['targets']),'total_targets':len(targets),'updated_unix':time.time()})
 motion.update(measured_targets=sum(v['sampled_clear'] is not None for v in motion['targets'].values()),
  passed_targets=sum(v['sampled_clear'] is True for v in motion['targets'].values()),
  scope='Every observed local/workflow pose; exact solids; discrete sampling does not certify continuous clearance.')
 # No observed motion in a valid local test is a failed physical demonstration.
 motion_scores={}
 for id,row in motion['targets'].items():
  motion_scores[id]=0. if row['overlaps'] else (None if row['unresolved'] else float(bool(row['sampled_clear'] and row['moving_components'])))
 motion_macro=macro(motion_scores,roles)
 result={'static':stat,'penetration':penetration,'support':support_macro,'motion':motion,'motion_score':motion_macro}
 write(folder/'geometry.json',result);return result
if __name__=='__main__':
 import sys
 f=OUT/sys.argv[1]
 observations(f)
 if not (f/'geometry.json').exists():geometry(f)

