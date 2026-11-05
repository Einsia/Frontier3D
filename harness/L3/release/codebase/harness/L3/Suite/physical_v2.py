"""Asset support, measured overlap extent and rigid-assembly motion.

Scoring units are geometric assets and required interaction roles. Invisible
collision helpers do not count as visible geometry. All raw failures are kept.
"""
from pathlib import Path
from collections import defaultdict
import json,math,time,hashlib
import numpy as np
from .policy import ROOT,read,write
from harness.L3.MinecraftVillage.scene_geometry import Scene,instance_key,motion_measure
from harness.L3.MinecraftVillage.contact import contact
from src.evaluator.l2_support_chain import pieces,ContactBudget
from src.evaluator.l2_physical import NearbyParts

VERSION='l3-physical-assets-v2.2'

def weighted(values,weights):
    den=sum(weights)
    return sum(v*w for v,w in zip(values,weights))/den if den else None

def aggregate(scene,values,areas,roles,excluded=()):
    rows=defaultdict(list);weights=defaultdict(list)
    for i,item in enumerate(scene.items):
        if i in excluded:continue
        rows[item['actor']].append(values[i]);weights[item['actor']].append(areas[i])
    entity={k:weighted(v,weights[k]) for k,v in rows.items()}
    groups=defaultdict(list)
    for key,role in roles.items():groups[role].append(entity.get(key,0.))
    role_scores={k:sum(v)/len(v) for k,v in groups.items()}
    required=sum(role_scores.values())/len(role_scores) if role_scores else None
    ids=[i for i,x in enumerate(scene.items) if x['actor'] not in roles and i not in excluded]
    scenery=weighted([values[i] for i in ids],[areas[i] for i in ids])
    valid=[v for v in [scenery,required] if v is not None]
    return {'score':sum(valid)/len(valid) if valid else None,'scene_score':scenery,'required_entities_score':required,
            'roles':role_scores,'entities':entity,'aggregation':'equal scene/required-role axes; surface-weighted asset fractions within scene/entity; equal required roles'}

def asset_geometry(scene):
    triangles=[];areas=[]
    for i,item in enumerate(scene.items):
        template=scene.templates[item['mesh']];a,o=scene.transforms[i]
        tri=(template['vertices']@a+o)[template['indices']]/100
        triangles.append(tri)
        areas.append(float(np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1).sum()/2))
    return triangles,np.array(areas)

class Surface:
    def __init__(self,xyz):
        from scipy.spatial import cKDTree
        self.xyz=xyz;self.centers=xyz.mean(1);self.radii=np.linalg.norm(xyz-self.centers[:,None,:],axis=2).max(1)
        self.low=xyz.min((0,1));self.high=xyz.max((0,1));self.tree=cKDTree(self.centers)

def grounding(scene,triangles,areas,roles,progress_path=None):
    bounds=scene.bounds/100;ext=bounds[:,1]-bounds[:,0]
    low=bounds[:,0].min(0);high=bounds[:,1].max(0)
    # Geometric datum: broad low shallow actual asset, independent of actor names.
    candidates=[i for i in range(len(ext)) if ext[i,2]<=.25*max(ext[i,:2]) and bounds[i,1,2]<=low[2]+.35*(high[2]-low[2])]
    inference='low_broad_asset'
    if not candidates:
        # Background mountains may extend below the inhabited terrain. Select
        # a low shallow asset relative to other shallow assets in that case,
        # rather than treating the mountain bottom as the scene floor.
        thin=[i for i in range(len(ext)) if ext[i,2]<=.25*max(ext[i,:2])]
        # Prefer the broadest shallow foundation. A median over assets would
        # let thousands of repeated paving pieces displace the actual ground.
        candidates=thin
        inference='low_broad_asset_background_relief_fallback'
    if not candidates:raise ValueError('No independently supported broad terrain datum')
    footprint=np.prod(ext[:,:2],axis=1);root=max(candidates,key=lambda i:footprint[i])
    roots={i for i in candidates if footprint[i]>=.15*footprint[root] and abs(bounds[i,1,2]-bounds[root,1,2])<=.02}
    # Broad surrounding landforms whose base reaches below the established
    # terrain datum are terrain, even outside the finite ground mesh. They do
    # not become floating architecture because a scene has no infinite floor.
    roots.update(i for i in range(len(ext)) if footprint[i]>=.15*footprint[root] and bounds[i,0,2]<=bounds[root,1,2]+.02)
    near=NearbyParts(bounds[:,0],bounds[:,1]);surfaces={};cache={};budget=ContactBudget(maximum=500_000_000)
    aligned={i for i,b in enumerate(scene.boxes) if b is not None and np.all(np.sum(np.abs(b[2])>1e-12,axis=1)==1)}
    reached=set(roots);front=list(roots);edges=[];last_progress=time.monotonic();visited=0
    def connects(i,j):
        a,b=scene.boxes[i],scene.boxes[j]
        if a is not None and b is not None:
            if i in aligned and j in aligned:
                # For axis-aligned cuboids this is exactly the same SAT test,
                # without constructing 15 redundant separating axes.
                return bool(np.all(np.maximum(bounds[i,0]-bounds[j,1],bounds[j,0]-bounds[i,1])<=.02000001))
            from harness.L3.MinecraftVillage.scene_geometry import sat_depth
            # Exact OBB contact/embedding, including containment. AABB is only broad phase.
            return sat_depth(a,b)>=-2.000001
        for k in [i,j]:
            if k not in surfaces:surfaces[k]=Surface(triangles[k])
        if contact(surfaces[i],surfaces[j],.02,budget):return True
        # Fully embedded closed parts have no surface intersection but are attached.
        if np.all(np.minimum(scene.bounds[i,1],scene.bounds[j,1])>np.maximum(scene.bounds[i,0],scene.bounds[j,0])):
            try:return (scene.solid(i)^scene.solid(j)).volume()>1e-6
            except (ValueError,RuntimeError,TypeError):pass
        return False
    while front:
        i=front.pop();visited+=1
        for j in near.query(i,.02):
            if j in reached:continue
            if connects(i,j):reached.add(j);front.append(j);edges.append([i,j])
        if progress_path and time.monotonic()-last_progress>20:
            write(progress_path,{'reached':len(reached),'visited':visited,'total':len(scene.items),'triangle_pairs':budget.pairs,'time':time.time()});last_progress=time.monotonic()
    values=[float(i in reached) for i in range(len(scene.items))]
    return {**aggregate(scene,values,areas,roles,roots),'ground_inference':inference,'roots':[list(instance_key(scene.items[i])) for i in roots],
            'root_bounds_m':[bounds[i].tolist() for i in roots],'contact_edges':edges,
            'unsupported_assets':[{'instance':list(instance_key(x)),'bounds_m':bounds[i].tolist(),'surface_area_m2':areas[i]} for i,x in enumerate(scene.items) if i not in reached],
            'asset_count':len(scene.items),'unsupported_asset_count':len(scene.items)-len(reached),
            'scope':'Rendered mesh assets connected to a geometric ground datum; surface contact or closed-solid embedding. Internal disconnected surfaces within one authored mesh are one asset; not load-bearing certification.'}

def relative_signatures(folder,target):
    paths=sorted(folder.glob('trajectory_*.json'));first=folder/'initial.json'
    if not paths or not first.exists():return {}
    initial=read(first);base={c['name']:c for e in initial['entities'] if e['id']==target for c in e['components']}
    signatures={k:hashlib.sha256() for k in base};valid=set(base)
    for path in paths:
        state={c['name']:c for e in read(path)['entities'] if e['id']==target for c in e['components']}
        for key in list(valid):
            b=base[key];s=state.get(key)
            if s is None or not all(k in s and k in b for k in ['axis_x','axis_y','axis_z']):valid.remove(key);continue
            a=np.array([b['axis_x'],b['axis_y'],b['axis_z']],float)
            if abs(np.linalg.det(a))<1e-12:valid.remove(key);continue
            d=np.linalg.solve(a,np.array([s['axis_x'],s['axis_y'],s['axis_z']],float));shift=np.array(s['position_cm'])-np.array(b['position_cm'])@d
            values=np.round(np.r_[d.ravel(),shift],4);values[values==0]=0;signatures[key].update(values.tobytes())
    return {k:signatures[k].hexdigest() for k in valid}

def penetration(scene,raw,areas,roles,episodes):
    indices={instance_key(x):i for i,x in enumerate(scene.items)};signatures={};excluded=[];violations=[];fractions=np.zeros(len(scene.items));volumes={}
    def volume(i):
        if i not in volumes:
            box=scene.boxes[i]
            volumes[i]=float(8*np.prod(box[1])) if box is not None else scene.solid(i).volume()
        return volumes[i]
    for row in raw['overlaps']:
        ka,kb=tuple(row['left']),tuple(row['right'])
        if ka not in indices or kb not in indices:excluded.append({**row,'reason':'nonvisible render helper'});continue
        i,j=indices[ka],indices[kb];actor=ka[0]
        if actor==kb[0]:
            if actor not in roles:excluded.append({**row,'reason':'static assembly union'});continue
            if actor not in signatures:signatures[actor]=relative_signatures(episodes/actor.replace('.','_'),actor)
            sig=signatures[actor]
            if ka[1] in sig and kb[1] in sig and sig[ka[1]]==sig[kb[1]]:
                excluded.append({**row,'reason':'invariant relative component pose over all recorded action frames'});continue
        try:
            vi,vj=volume(i),volume(j)
            intersection=(scene.solid(i)^scene.solid(j)).volume()
            if intersection<0:raise ValueError('Negative solid intersection')
            fi,fj=min(1,intersection/max(vi,1e-12)),min(1,intersection/max(vj,1e-12))
        except (ValueError,RuntimeError,TypeError):
            # Open-surface crossing is a real detected defect; never invent volume.
            intersection=None;fi=fj=1.
        fractions[i]=min(1,fractions[i]+fi);fractions[j]=min(1,fractions[j]+fj)
        violations.append({**row,'intersection_cm3':intersection,'left_affected_fraction':fi,'right_affected_fraction':fj})
    return {**aggregate(scene,1-fractions,areas,roles),'violations':violations,'allowed_assembly':excluded,
            'scope':'Surface-weighted intersecting volume fractions per visible solid asset. Sum of overlap fractions capped at one; open-surface proper crossings count as affected assets. Same rigid assembly contacts excluded by observed pose invariance.'}

def measure(source,output,roles,episodes,old):
    output.mkdir(exist_ok=True,parents=True);export=read(source)
    visible={**export,'instances':[x for x in export['instances'] if x.get('visible',True) and x.get('role')!='water']}
    scene=Scene(visible,open_surface_fallback=True);triangles,areas=asset_geometry(scene)
    start=time.time();write(output/'physical-input.json',{'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'version':VERSION,'roles':roles,'hidden_instances_excluded':len(export['instances'])-len(scene.items),'started_unix':start})
    support_path=output/'support-v2.2.json'
    prior_support=output/'support-v2.1.json'
    if not support_path.exists() and prior_support.exists():
        prior=read(prior_support)
        if not prior.get('ground_inference','').endswith('fallback'):write(support_path,prior)
    if not support_path.exists():write(support_path,grounding(scene,triangles,areas,roles,output/'support-progress.json'))
    print(output,'grounding complete',time.time()-start,flush=True)
    stat=old.get('static',old)
    pen_path=output/'penetration.json'
    if not pen_path.exists():write(pen_path,penetration(scene,stat,areas,roles,episodes))
    print(output,'penetration complete',time.time()-start,flush=True)
    targets=list(old['motion']['targets']);motion={}
    for target in targets:
        p=output/'motion'/(target+'.json')
        if not p.exists():write(p,motion_measure(scene,episodes,targets=[target],stop_on_failure=True,rigid_assemblies=True)['targets'][target])
        motion[target]=read(p)
    values={k:(0. if r['overlaps'] else None if r['unresolved'] else float(bool(r['sampled_clear'] and r['moving_components']))) for k,r in motion.items()}
    groups=defaultdict(list)
    for k,v in values.items():groups[roles.get(k,k)].append(v)
    scores={k:sum(v)/len(v) if all(x is not None for x in v) else None for k,v in groups.items()}
    score=sum(scores.values())/len(scores) if scores and all(x is not None for x in scores.values()) else None
    result={'version':VERSION,'support':read(support_path),'penetration':read(pen_path),
            'motion':{'targets':motion,'roles':scores,'score':score},'seconds':time.time()-start}
    write(output/'physical-summary.json',result);return result
