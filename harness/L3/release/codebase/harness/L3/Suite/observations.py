"""Physical observations and fixed end-state predicates. Candidate state text is never scored."""
import math
import numpy as np
from .policy import POLICY
def entities(frame):return {e['id']:e for e in frame.get('entities',[])}
def pos(frame,id):return np.array(entities(frame).get(id,{}).get('position_cm',[math.nan]*3),float)
def parts(frame,id):return {c['name']:c for c in entities(frame).get(id,{}).get('components',[]) if c.get('visible',False)}
def bounds(frame,id):
 cs=list(parts(frame,id).values())
 if not cs:return None
 low=np.array([c['bounds_center_cm'] for c in cs])-np.array([c['bounds_extent_cm'] for c in cs])
 high=np.array([c['bounds_center_cm'] for c in cs])+np.array([c['bounds_extent_cm'] for c in cs])
 return np.array([low.min(0),high.max(0)])
def inside(frame,item,dest,tol=15):
 b=bounds(frame,dest);p=pos(frame,item)
 return bool(b is not None and np.isfinite(p).all() and parts(frame,item) and np.all(p>=b[0]-tol) and np.all(p<=b[1]+tol))
def inventory(frame):
 return {i['actor']+':'+k:v for i in frame.get('trusted_inventory',[]) for k,v in i.get('counts',{}).items()}
def changed(a,b,id):
 aa=entities(a).get(id);bb=entities(b).get(id)
 if not aa or not bb:return False
 ca,cb=parts(a,id),parts(b,id)
 if set(ca)!=set(cb):return True
 for name in ca:
  for key in ['position_cm','rotation_deg','axis_x','axis_y','axis_z']:
   if not np.allclose(ca[name].get(key,[0]*3),cb[name].get(key,[0]*3),atol=.1,rtol=0):return True
  if ca[name].get('collision')!=cb[name].get('collision'):return True
 if aa.get('lights')!=bb.get('lights'):return True
 return False
def physical_effect(a,b,id,required):
 if changed(a,b,id):return True
 # Receptacles have static walls: score changes to actual item occupancy, not a "contents" string.
 if any(inside(a,x,id)!=inside(b,x,id) for x in required if x!=id):return True
 return False
def travelled(frames,id,minimum=100):
 ps=[pos(f,id) for f in frames];ps=[p for p in ps if np.isfinite(p).all()]
 return bool(ps and max(np.linalg.norm(p-ps[0]) for p in ps)>=minimum)
def goals(key,initial,final,frames,bindings):
 rows=[]
 def add(name,passed,detail=''):rows.append({'name':name,'passed':bool(passed),'evidence':detail})
 def contained(item,dest):add(item+' → '+dest,inside(final,item,dest), 'final observed item center within visible destination geometry bounds + 15 cm')
 def returned(id,tol=150):add(id+' returned',np.linalg.norm(pos(final,id)-pos(initial,id))<=tol)
 def moved(id):add(id+' physically transported',travelled(frames,id,300))
 def evolved(id):add(id+' mechanism physically changed',any(changed(initial,f,id) for f in frames))
 def lights(frame,id):return sum(float(x.get('intensity',0)) for x in entities(frame).get(id,{}).get('lights',[]) if x.get('visible'))
 if key=='l3-g02':
  add('key removed from box',not inside(final,'item.key','storage.key_box') and any('side_key' in k and v>0 for k,v in inventory(final).items()))
  add('crate reaches upper floor',pos(final,'cargo.crate')[2]-pos(initial,'cargo.crate')[2]>250)
  evolved('lift.main');evolved('gate.shortcut');evolved('shortcut.lever')
 elif key=='l3-g03':
  for item,dest in [('cargo.flour','storage.01'),('cargo.tools','storage.02'),('cargo.bottles','storage.03')]:contained(item,dest)
  moved('cart.freight');returned('cart.freight');add('stable gate closed again',not changed(initial,final,'gate.stable'))
 elif key=='l3-g04':
  for id in ['cargo.crate.01','cargo.crate.02']:
   moved(id);add(id+' unloaded',not inside(final,id,'platform.cargo'))
  evolved('lift.freight');evolved('platform.cargo');evolved('dock.latch')
 elif key=='l3-g05':
  for id in ['basin.a.water','basin.b.water','platform.a','platform.b']:evolved(id)
  add('basin A remains raised',pos(final,'basin.a.water')[2]>pos(initial,'basin.a.water')[2]+100)
  add('basin B drained',abs(pos(final,'basin.b.water')[2]-pos(initial,'basin.b.water')[2])<40)
 elif key=='l3-g06':
  for i in range(1,4):contained(f'supply.bundle.{i:02}','cargo.crate')
  contained('item.tools','storage.lodge');evolved('bridge.river');evolved('lift.ruins');moved('cargo.crate')
  add('counterweight on plate',inside(final,'counterweight','plate.bridge',100))
 elif key=='l3-e01':
  for id in ['garment.01','garment.02']:contained(id,'basket.laundry')
  for id in ['item.plate','item.cup']:contained(id,'storage.dishes')
  contained('item.garden_tool','storage.garden')
  add('laundry passed through washer',all(any(inside(f,id,'washer.door',70) for f in frames) for id in ['garment.01','garment.02']))
  # Public initial bottle supply is three; the pawn inventory component starts empty.
  remaining=[v for k,v in inventory(final).items() if k.endswith(':detergent_doses')]
  add('one detergent dose consumed',remaining==[2], 'three supplied doses minus one used dose; trusted final inventory')
 elif key=='l3-e02':
  for cat,dest in [('milk','storage.chilled'),('tin','storage.ambient'),('bottle','storage.fragile')]:
   ids=[f'stock.{cat}.{i:02}' for i in range(1,5)]
   add(cat+' three stored',sum(inside(final,x,dest) for x in ids)==3)
   add(cat+' one returned',sum(inside(final,x,'returns.counter') for x in ids)==1)
  moved('cart.stock');returned('cart.stock')
 elif key=='l3-e03':
  for id in ['part.base','part.bracket','part.fastener.01','part.fastener.02']:contained(id,'packing.box')
  contained('tool.driver','cabinet.tools');moved('pallet');returned('truck.pallet')
  evolved('vice.bench');evolved('door.loading')
 elif key=='l3-e04':
  for cat,crate in [('a','crate.01'),('b','crate.02')]:
   ids=[f'fruit.variety_{cat}.{i:02}' for i in range(1,7)]
   count=sum(inside(final,x,crate) for x in ids)
   add(cat+' sorted crate',count in [5,6])
   add(cat+' was weighed with six fruit',any(sum(inside(f,x,crate) for x in ids)==6 and np.linalg.norm(pos(f,crate)-pos(f,'scale.bench'))<150 for f in frames))
   moved(crate)
  all_ids=[f'fruit.variety_{cat}.{i:02}' for cat in ['a','b'] for i in range(1,7)]
  add('one fruit removed',sum(any(inside(final,x,c) for c in ['crate.01','crate.02']) for x in all_ids)==11)
  evolved('valve.nursery');add('orchard valve unchanged',all(not changed(initial,f,'valve.orchard') for f in frames))
 elif key=='l3-e05':
  for i in range(1,7):
   contained(f'towel.{i:02}',f'drawer.bedside.{i:02}');contained(f'return.container.{i:02}','return.bin')
  evolved('bed.room03');evolved('curtain.room03');returned('card.supply');returned('cart.supply')
 elif key=='l3-e06':
  contained('filter.a','return.bin');contained('filter.spare','housing.a')
  for id in ['line.b.inlet','line.b.outlet','housing.b']:add(id+' unchanged',all(not changed(initial,f,id) for f in frames))
  evolved('housing.a');add('housing A closed again',not changed(initial,final,'housing.a'));add('pump control restored',restored_control(initial,final,frames,'pump.power'))
 elif key=='l3-r01':
  for id in ['case.01','case.02','barrier.01','barrier.02','barrier.03','barrier.04']:moved(id);returned(id,300)
  for id in ['light.group.01','light.group.02']:
   add(id+' switched on',max(lights(f,id) for f in frames)>lights(initial,id)+1)
   add(id+' switched off',lights(final,id)<=lights(initial,id)+1)
  add('third light stays off',all(lights(f,'light.group.03')<=lights(initial,'light.group.03')+1 for f in frames))
  evolved('gate.main.01');evolved('gate.main.02')
 elif key=='l3-r02':
  for i in range(1,4):
   add(f'stall {i} receives two units',sum(inside(final,f'cargo.{j:02}',f'stall.storage.{i:02}') for j in range(1,7))==2)
  evolved('gangway');add('gangway stowed again',not changed(initial,final,'gangway'))
  moved('cart.delivery');returned('cart.delivery')
 elif key=='l3-r03':
  bags=[f'bag.{i:02}' for i in range(1,7)]
  add('four bags delivered',sum(inside(final,x,'bay.platform') for x in bags)==4)
  add('one bag in locker',sum(any(inside(final,x,d) for d in ['locker.01','locker.02']) for x in bags)==1)
  add('one bag on cart',sum(inside(final,x,'cart.luggage') for x in bags)==1)
  moved('cart.luggage');returned('cart.luggage');evolved('lift.concourse');evolved('shutter.service')
 else:raise ValueError('No frozen workflow predicates for '+key)
 return rows



def negative_unchanged(control,before,after,id):
 if inventory(before)!=inventory(after):return False
 a,b,c=parts(control,id),parts(before,id),parts(after,id)
 if set(a)!=set(b) or set(b)!=set(c):return False
 if entities(before).get(id,{}).get('lights')!=entities(after).get(id,{}).get('lights'):return False
 ratio=(after['time']-before['time'])/max(.01,before['time']-control['time'])
 for name in b:
  if b[name].get('collision')!=c[name].get('collision'):return False
  for field,tol in [('position_cm',3.),('rotation_deg',5.)]:
   x,y,z=[np.array(row[name].get(field,[0,0,0]),float) for row in [a,b,c]]
   delta=y-x
   if field=='rotation_deg':delta=(delta+180)%360-180
   error=z-(y+delta*ratio)
   if field=='rotation_deg':error=(error+180)%360-180
   if np.max(np.abs(error))>tol:return False
 return True

def restored_control(initial,final,frames,id):
 start=parts(initial,id);end=parts(final,id)
 if set(start)!=set(end):return False
 moving=set()
 for frame in frames[1:5]:
  for name,c in parts(frame,id).items():
   if name in start and (not np.allclose(c['position_cm'],start[name]['position_cm'],atol=.1) or not np.allclose(c['rotation_deg'],start[name]['rotation_deg'],atol=.1)):moving.add(name)
 stable=set(start)-moving
 for name in stable:
  for k in ['position_cm','rotation_deg']:
   if not np.allclose(start[name][k],end[name][k],atol=.1):return False
 if entities(initial).get(id,{}).get('lights')!=entities(final).get(id,{}).get('lights'):return False
 return bool(stable) or (len(frames)>1 and changed(frames[-2],final,id))
