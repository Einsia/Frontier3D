"""Evaluator-authored probes; submitted routes are untrusted executable inputs, not oracles."""
import copy, math
from .policy import read,write
PAIRS=[('close','open'),('off','on'),('retract','extend'),('stow','deploy'),('release','engage'),('unclamp','clamp'),('lower','raise'),('unlatch','latch')]
from .binding_hints import vector3
def pose(b):
 value=b.get('approach_cm')
 return value if vector3(value) else None
def steps_plan(steps):return {'version':1,'steps':steps}
def view_plan(bindings):
 s=[{'op':'snapshot','name':'scene_initial'},{'op':'export_geometry','name':'scene_geometry'}]
 meta={}
 for prefix,views in [('view',bindings.get('views',{})),('reference',bindings.get('reference_views',{}))]:
  for i,(key,v) in enumerate(views.items()):
   if not isinstance(v,dict) or not all(k in v for k in ['position_cm','look_cm']):continue
   name=f'{prefix}_{i:02}'
   s.extend([{'op':'camera','name':name+'_camera','position_cm':v['position_cm'],'target_cm':v['look_cm'],'horizontal_fov_deg':v.get('horizontal_fov_deg',60)},
             {'op':'snapshot','name':name+'_pose'},{'op':'capture','name':name}])
   meta[name]={'label':key,'kind':prefix,'camera':v,'yaw_delta':0}
   if prefix=='reference':
    for suffix,degrees in [('left',-12),('right',12)]:
     angle=math.radians(degrees);dx=v['position_cm'][0]-v['look_cm'][0];dy=v['position_cm'][1]-v['look_cm'][1]
     vv=copy.deepcopy(v);vv['position_cm']=[v['look_cm'][0]+dx*math.cos(angle)-dy*math.sin(angle),v['look_cm'][1]+dx*math.sin(angle)+dy*math.cos(angle),v['position_cm'][2]]
     variant=name+'_'+suffix
     s.extend([{'op':'camera','name':variant+'_camera','position_cm':vv['position_cm'],'target_cm':vv['look_cm'],'horizontal_fov_deg':vv.get('horizontal_fov_deg',60)},
               {'op':'snapshot','name':variant+'_pose'},{'op':'capture','name':variant}])
     meta[variant]={'label':key,'kind':prefix,'camera':vv,'yaw_delta':degrees}
 return steps_plan(s),meta
def workflow_plan(bindings,contract,observed_ids=()):
 raw=bindings.get('workflow',[]);waypoints={}
 if isinstance(raw,dict):
  declared=raw.get('waypoints',[])
  if isinstance(declared,list):
   for point in declared:
    if not isinstance(point,dict):continue
    labels=[point[k] for k in ('name','id') if isinstance(point.get(k),str)]
    for label in labels:
     value=point.get('position_cm')
     if label in waypoints and waypoints[label]!=value:waypoints[label]=None
     elif label not in waypoints:waypoints[label]=copy.deepcopy(value)
  raw=raw.get('steps',[])
 allowed={'walk_to','look','look_entity','interact','invoke','wait','move'}
 entities={e['id']:e for e in contract['entities']}
 callable_ids=set(entities)|set(bindings.get('entities',{}))|set(observed_ids)
 s=[];meta=[];rejected=copy.deepcopy(bindings.get('_route_translation_rejected',[]))
 for i,step in enumerate(raw):
  if not isinstance(step,dict):
   rejected.append({'index':i,'reason':'non-executable route description','step':step});continue
  if step.get('op') in {'snapshot','capture','camera','probe'}:continue
  if step.get('op') not in allowed:
   rejected.append({'index':i,'reason':'forbidden route operation','step':step});continue
  submitted_step=step
  step=copy.deepcopy(step)
  if step.get('op')=='walk_to' and 'target_cm' not in step:
   aliases=[step[k] for k in ('position_cm','target') if k in step and isinstance(step[k],list)]
   if isinstance(step.get('waypoint'),str) and step['waypoint'] in waypoints:aliases.append(waypoints[step['waypoint']])
   if aliases and all(v==aliases[0] for v in aliases):
    step['target_cm']=copy.deepcopy(aliases[0])
  if step.get('op') in {'interact','invoke','look_entity'} and 'target' not in step:
   aliases=[step[k] for k in ('entity_id','entity') if k in step]
   if aliases and all(isinstance(v,str) and v==aliases[0] for v in aliases):
    step['target']=aliases[0]
   elif aliases:
    rejected.append({'index':i,'reason':'invalid or conflicting entity aliases','step':submitted_step});continue
  vector_key={'walk_to':'target_cm','look':'target_cm','move':'direction'}.get(step.get('op'))
  if vector_key:
   vector=step.get(vector_key)
   if not (isinstance(vector,list) and len(vector)==3 and all(type(v) in (int,float) and math.isfinite(v) for v in vector)):
    rejected.append({'index':i,'reason':'invalid or missing '+vector_key+'; expected three finite numbers','step':submitted_step});continue
  if step.get('op') in {'walk_to','move','wait'} and 'seconds' in step:
   duration=step['seconds']
   if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=30:
    rejected.append({'index':i,'reason':'invalid seconds; expected finite number from 0 to 30','step':step});continue
  x=copy.deepcopy(step);x['name']=f'w{i:04}'
  if x['op'] in {'invoke','interact'} and (x.get('target') not in callable_ids or not isinstance(x.get('action'),str) or not x['action'].strip() or len(x['action'])>128):
   rejected.append({'index':i,'reason':'unregistered target or invalid action string','step':step});continue
  before=x['name']+'_before';after=x['name']+'_after'
  s.append({'op':'snapshot','name':before});s.append(x)
  if x['op'] in {'invoke','interact'}:s.append({'op':'wait','name':x['name']+'_settle','seconds':.3})
  s.append({'op':'snapshot','name':after})
  row={'step':x,'before':before,'after':after}
  if step!=submitted_step:row['submitted_step']=submitted_step;row['input_normalization']='exact submitted destination/entity ID copied to observer field; no inferred values'
  meta.append(row)
 return steps_plan(s),{'steps':meta,'rejected':rejected,'candidate_route_used_as':'navigation/action proposal only; no candidate assertions accepted'}
def local_plan(bindings,contract):
 s=[];meta=[];constraints=[]
 prerequisite_cases={
 'l3-g02':[('door.side','open',''),('lift.barrier.02','open',''),('gate.shortcut','open','')],
 'l3-g03':[('cargo.flour','pick_up','')],
 'l3-g04':[('lift.freight','travel','upper'),('lift.door.02','open','')],
 'l3-g05':[],
 'l3-g06':[('winch.bridge','lower','')],
 'l3-e01':[('washer.controls','start',''),('washer.controls','add_detergent','missing.item')],
 'l3-e02':[('scanner.counter','scan','missing.item')],
 'l3-e03':[('cabinet.tools','open',''),('part.fastener.01','fasten','')],
 'l3-e04':[],
 'l3-e05':[('cabinet.supply.01','open',''),('cabinet.supply.02','open',''),('bed.room03','set_height','50000')],
 'l3-e06':[('housing.a','unlatch',''),('filter.a','remove','')],
 'l3-r01':[('case.01','put_into','missing.receptacle')],
 'l3-r02':[('boarding.gate.01','open',''),('boarding.gate.02','open','')],
 'l3-r03':[('gate.ticket.01','open',''),('lift.door.02','open','')]
 }
 for i,(id,action,arg) in enumerate(prerequisite_cases[contract['task_key']]):
  b=bindings.get('entities',{}).get(id,{})
  if not pose(b):continue
  name=f'constraint_{i:02}'
  s.extend([{'op':'fixture','purpose':'local_test_setup','name':name+'_setup','position_cm':pose(b)},
   {'op':'snapshot','name':name+'_control'},
   {'op':'wait','name':name+'_control_wait','seconds':.25},
   {'op':'snapshot','name':name+'_before'},
   {'op':'invoke','name':name,'target':id,'action':action,'argument':arg},
   {'op':'wait','name':name+'_wait','seconds':.25},
   {'op':'snapshot','name':name+'_after'}])
  constraints.append({'name':name,'id':id,'action':action,'argument':arg,'expected':'no physical effect under unmet initial prerequisite or invalid argument'})
 for index,entity in enumerate(contract['entities']):
  id=entity['id'];b=bindings.get('entities',{}).get(id,{})
  prefix=f'e{index:03}';actions=entity['actions']
  loc=pose(b)
  if not loc:meta.append({'id':id,'role':entity['role'],'binding_missing':True});continue
  row={'id':id,'role':entity['role'],'prefix':prefix,'actions':actions,'binding':b,'positive':[]}
  first=actions[0] if actions else None
  initial=entity.get('initial','').lower()
  if initial.startswith(('open','on','running')):
   first=next((a for a in ['close','off'] if a in actions),first)
  if first:
   far=[float(loc[0])+5000,float(loc[1])+5000,float(loc[2])]
   s.extend([{'op':'fixture','purpose':'local_test_setup','name':prefix+'_far','position_cm':far},
     {'op':'snapshot','name':prefix+'_control_before'},
     {'op':'wait','name':prefix+'_control_wait','seconds':.25},
     {'op':'snapshot','name':prefix+'_neg_before'},
     {'op':'invoke','name':prefix+'_neg','target':id,'action':first,'argument':''},
     {'op':'wait','name':prefix+'_neg_wait','seconds':.25},
     {'op':'snapshot','name':prefix+'_neg_after'}])
  s.extend([{'op':'fixture','purpose':'local_test_setup','name':prefix+'_setup','position_cm':loc},
            {'op':'look','name':prefix+'_look','target_cm':b.get('look_cm',loc)},
            {'op':'snapshot','name':prefix+'_before'}])
  chosen=[]
  for reverse,forward in PAIRS:
   if forward in actions and reverse in actions:chosen=[reverse,forward,reverse];break
  if not chosen:
   if 'pick_up' in actions:chosen=['pick_up','drop']
   elif actions:chosen=[actions[0]]
  for j,action in enumerate(chosen):
   arg=''
   if action in {'call','travel'}:arg='upper'
   if action in {'set_height','set_head_angle'}:arg='120' if action=='set_height' else '35'
   name=prefix+f'_a{j}'
   s.extend([{'op':'snapshot','name':name+'_before'},
      {'op':'invoke','name':name,'target':id,'action':action,'argument':arg},
      {'op':'wait','name':name+'_wait','seconds':2},
      {'op':'snapshot','name':name+'_after'}])
   row['positive'].append({'name':name,'action':action})
  if 'crossing_from_cm' in b and 'crossing_to_cm' in b and 'open' in actions:
   s.extend([{'op':'invoke','name':prefix+'_open_for_walk','target':id,'action':'open','argument':''},
    {'op':'wait','name':prefix+'_walk_settle','seconds':2},
    {'op':'fixture','purpose':'local_test_setup','name':prefix+'_walk_start','position_cm':b['crossing_from_cm']},
    {'op':'walk_to','name':prefix+'_walk','target_cm':b['crossing_to_cm'],'seconds':8},
    {'op':'snapshot','name':prefix+'_walk_after'}])
   row['walk_target']=b['crossing_to_cm']
  invalid=prefix+'_invalid'
  s.extend([{'op':'snapshot','name':invalid+'_control'},{'op':'wait','name':invalid+'_control_wait','seconds':.25},
   {'op':'snapshot','name':invalid+'_before'},{'op':'invoke','name':invalid,'target':id,'action':'__invalid_benchmark_action__','argument':''},
   {'op':'wait','name':invalid+'_wait','seconds':.25},{'op':'snapshot','name':invalid+'_after'}])
  row['invalid_probe']=invalid
  meta.append(row)
 return steps_plan(s),{'entities':meta,'constraints':constraints}

