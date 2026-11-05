"""Whole-export solid overlap and all-required-mechanism motion measurements.

Every visible mesh instance is considered, including non-blocking geometry and
parts of the same actor. Cuboids use exact OBB SAT; other closed meshes use
Manifold intersection volume. Unsupported geometry is never silently passed.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import itertools
import json
import math
from pathlib import Path
import numpy as np
from .penetration import box_template
from .protocol import DOORS, CHESTS, digest, write_json


def sat_depth(a, b):
    ca, ha, ba = a
    cb, hb, bb = b
    axes=np.concatenate([ba, bb, np.cross(ba[:,None,:],bb[None,:,:]).reshape(-1,3)])
    norms=np.linalg.norm(axes,axis=1); axes=axes[norms>1e-9]/norms[norms>1e-9,None]
    return float((ha@np.abs(ba@axes.T)+hb@np.abs(bb@axes.T)-np.abs((cb-ca)@axes.T)).min())


def instance_key(item):
    return (item['actor'], item['component'], item.get('instance', item.get('index',0)))


class Scene:
    def __init__(self, exported, *, open_surface_fallback=False):
        self.open_surface_fallback=open_surface_fallback;self.overlap_cache={};self.transformed_solids={};self.surface_cache={}
        self.invalid_static_solids={}; self.exported=exported; self.items=exported['instances']; self.templates={}; self.solid_cache={}
        for name, mesh in exported['meshes'].items():
            try: box=box_template(mesh)
            except (ValueError,IndexError): box=None
            self.templates[name]={'vertices':np.asarray(mesh['vertices_cm'],float),
                                  'indices':np.asarray(mesh['indices'],int).reshape(-1,3), 'box':box}
        self.transforms=[(np.asarray([i['axis_x'],i['axis_y'],i['axis_z']],float),np.asarray(i['origin_cm'],float)) for i in self.items]
        self.boxes=[self.box(i,*t) for i,t in enumerate(self.transforms)]
        self.bounds=np.array([self.bounds_at(i,*t) for i,t in enumerate(self.transforms)])

    def bounds_at(self, index, axes, origin):
        v=self.templates[self.items[index]['mesh']]['vertices']@axes+origin
        return np.array([v.min(0),v.max(0)])

    def box(self,index,axes,origin):
        template=self.templates[self.items[index]['mesh']]['box']
        if template is None:return None
        scales=np.linalg.norm(axes,axis=1)
        if np.any(scales<1e-9):return None
        basis=axes/scales[:,None]
        if not np.allclose(basis@basis.T,np.eye(3),atol=1e-6):return None
        mid,half=template
        return mid@axes+origin,half*scales,basis

    def solid(self,index,transform=None):
        # Static transforms and exported mesh data are immutable for this Scene.
        # Reuse a failed validation just as we reuse a successfully built solid.
        # Keep transformed poses separate: a different pose must be evaluated.
        if transform is None and index in self.invalid_static_solids:
            raise ValueError(self.invalid_static_solids[index])
        try:
            return self._solid(index,transform)
        except ValueError as error:
            if transform is None:self.invalid_static_solids[index]=str(error)
            raise

    def _solid(self,index,transform=None):
        import manifold3d as manifold
        if transform is None and index in self.solid_cache:return self.solid_cache[index]
        axes,origin=transform or self.transforms[index]
        template=self.templates[self.items[index]['mesh']]
        v=template['vertices']@axes+origin
        unique,inverse=np.unique(v,axis=0,return_inverse=True)
        faces=inverse[template['indices']]
        # Boundary/non-manifold topology is not a closed solid. Reject it before
        # the native constructor, which can segfault on open procedural meshes.
        edges=np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1)
        _,counts=np.unique(edges,axis=0,return_counts=True)
        if not len(faces) or np.any(counts!=2) or np.any(edges[:,0]==edges[:,1]):
            raise ValueError('Not a closed valid solid')
        # UE triangle winding can be the opposite of Manifold's convention.
        triangles=unique[faces]
        volume=np.einsum('ij,ij->i',triangles[:,0],np.cross(triangles[:,1],triangles[:,2])).sum()/6
        if volume<0:faces=faces[:,::-1]
        mesh=manifold.Mesh64(vert_properties=unique.astype(np.float64),tri_verts=faces.astype(np.uint64),tolerance=0.0001)
        mesh.merge()
        result=manifold.Manifold(mesh)
        if result.status()!=manifold.Error.NoError or result.is_empty():raise ValueError('Not a closed valid solid')
        if transform is None:self.solid_cache[index]=result
        return result

    def overlap(self,i,j,tolerance_cm,transform_i=None,transform_j=None,volume_tolerance_cm3=8):
        def pose(k,t):
            a,o=t if t is not None else self.transforms[k]
            return (np.asarray(a).tobytes(),np.asarray(o).tobytes())
        key=(i,j,tolerance_cm,volume_tolerance_cm3,pose(i,transform_i),pose(j,transform_j))
        if key not in self.overlap_cache:
            result=self._overlap(i,j,tolerance_cm,transform_i,transform_j,volume_tolerance_cm3)
            if len(self.overlap_cache)>200000:self.overlap_cache.clear()
            self.overlap_cache[key]=result
        return self.overlap_cache[key]

    def _overlap(self,i,j,tolerance_cm,transform_i=None,transform_j=None,volume_tolerance_cm3=8):
        a=self.boxes[i] if transform_i is None else self.box(i,*transform_i)
        b=self.boxes[j] if transform_j is None else self.box(j,*transform_j)
        if a is not None and b is not None:
            depth=sat_depth(a,b)
            return {'method':'verified_cuboid_sat','violates':depth>tolerance_cm+1e-6,'depth_cm':max(0.,depth)}
        try:
            left=self.solid(i,transform_i);right=self.solid(j,transform_j)
            intersection=left^right
            if intersection.status().name!='NoError':raise ValueError('Invalid intersection')
            volume=intersection.volume()
            return {'method':'closed_mesh_intersection_volume','violates':volume>volume_tolerance_cm3,
                    'intersection_cm3':volume,'volume_tolerance_cm3':volume_tolerance_cm3,
                    'note':'Volume threshold is separate from the cuboid translation-depth threshold'}
        except (ImportError,ValueError,RuntimeError,TypeError) as error:
            if self.open_surface_fallback and isinstance(error,ValueError) and str(error)=='Not a closed valid solid':
                from harness.L3.Suite.open_surface import crossing
                def triangles(k,t):
                    a,o=t if t is not None else self.transforms[k]
                    key=(k,np.asarray(a).tobytes(),np.asarray(o).tobytes())
                    if key not in self.surface_cache:
                        if len(self.surface_cache)>2048:self.surface_cache.clear()
                        self.surface_cache[key]=(self.templates[self.items[k]['mesh']]['vertices']@a+o)[self.templates[self.items[k]['mesh']]['indices']]
                    return self.surface_cache[key]
                return crossing(triangles(i,transform_i),triangles(j,transform_j),tolerance_cm)
            return {'method':'unresolved','violates':None,'reason':str(error)}


def broad_pairs(bounds, cell_cm=200., max_cells=4096):
    """Conservative hash-grid broad phase; giant instances are compared separately."""
    buckets=defaultdict(list);large=[]
    for i,(low,high) in enumerate(bounds):
        a=np.floor(low/cell_cm).astype(int);b=np.floor(high/cell_cm).astype(int)
        if math.prod((b-a+1).tolist())>max_cells:large.append(i);continue
        for key in itertools.product(*(range(x,y+1) for x,y in zip(a,b))):buckets[key].append(i)
    seen=set()
    for ids in buckets.values():
        for i,j in itertools.combinations(ids,2):
            pair=(min(i,j),max(i,j))
            if pair not in seen:seen.add(pair);yield pair
    for i in large:
        for j in range(len(bounds)):
            if i==j:continue
            pair=(min(i,j),max(i,j))
            if pair not in seen:seen.add(pair);yield pair


def static_measure(scene, tolerance_cm=2., allowed=None, pair_budget=20_000_000):
    allowed=allowed or [];allow={}
    for rule in allowed:
        # Explicit instance pairs only. No whole-actor or wildcard exemption.
        left=tuple(rule['left']);right=tuple(rule['right'])
        if left==right or not rule.get('reason') or not rule.get('id'):raise ValueError('Invalid contact exemption')
        allow[frozenset((left,right))]=rule
    contacts=[];unresolved=[];per_actor=Counter();checked=0;broad=0;exemptions=[]
    for i,j in broad_pairs(scene.bounds):
        broad+=1
        if broad>pair_budget:raise RuntimeError('Pair budget exceeded; no complete score may be reported')
        low=np.maximum(scene.bounds[i,0],scene.bounds[j,0]);high=np.minimum(scene.bounds[i,1],scene.bounds[j,1])
        if np.any(high-low<=1e-6):continue
        checked+=1;result=scene.overlap(i,j,tolerance_cm)
        row={'left':list(instance_key(scene.items[i])),'right':list(instance_key(scene.items[j])),**result}
        if result['violates'] is None:unresolved.append(row)
        elif result['violates']:
            rule=allow.get(frozenset((tuple(row['left']),tuple(row['right']))))
            if rule and (result.get('depth_cm',math.inf)<=rule.get('max_depth_cm',-1) or result.get('intersection_cm3',math.inf)<=rule.get('max_intersection_cm3',-1)):
                exemptions.append(dict(row,rule=rule['id'],reason=rule['reason']))
            else:
                contacts.append(row)
                for actor in {scene.items[i]['actor'],scene.items[j]['actor']}:per_actor[actor]+=1
    return {'method':'whole_scene_solid_overlap_v1','instance_count':len(scene.items),
            'non_pawn_blocking_instances':sum(not x.get('blocks_pawn',False) for x in scene.items),
            'broad_phase_pairs':broad,'narrow_phase_pairs':checked,'tolerance_cm':tolerance_cm,
            'overlap_pair_count':len(contacts),'unresolved_pair_count':len(unresolved),
            'overlaps_by_actor':dict(per_actor),'overlaps':contacts,'unresolved':unresolved,'allowed_contacts':exemptions,
            'unexported_components':scene.exported.get('unexported_components',[]),
            'measurement_complete':not unresolved and not scene.exported.get('unexported_components'),'formal_score':None,
            'scope':'All exported instances, including same-actor pairs. Raw overlaps require frozen assembly/contact rules; this is not the full layout score.'}


def motion_measure(scene, episodes, targets=DOORS+CHESTS, tolerance_cm=2., *, stop_on_failure=False, rigid_assemblies=False):
    results={};by_actor=defaultdict(list)
    for i,item in enumerate(scene.items):by_actor[item['actor']].append(i)
    by_component=defaultdict(list)
    for i,item in enumerate(scene.items):by_component[(item['actor'],item['component'])].append(i)
    for target in targets:
        folder=episodes/target.replace('.','_')
        paths=sorted(folder.glob('trajectory_*.json'))
        contacts=[];unresolved=[];samples=0;moving=set();max_step=0.;previous={};previous_time=None;max_dt=0.;evaluated_frames=0;stopped=False
        first=folder/'initial.json'
        baseline=json.loads((first if first.exists() else paths[0]).read_bytes()) if paths else {'entities':[]}
        base_states={(e['id'],c['name']):c for e in baseline['entities'] for c in e['components']}
        relative={}
        for key,indices in by_component.items():
            state=base_states.get(key)
            if state and all(k in state for k in ['axis_x','axis_y','axis_z']):
                axes=np.asarray([state['axis_x'],state['axis_y'],state['axis_z']],float)
                if abs(np.linalg.det(axes))<1e-12:continue
                inverse=np.linalg.inv(axes);origin=np.asarray(state['position_cm'],float)
                for i in indices:
                    relative[i]=(scene.transforms[i][0]@inverse,(scene.transforms[i][1]-origin)@inverse)
        rigid_groups={}
        if rigid_assemblies:
            import hashlib
            signatures={key:hashlib.sha256() for key in by_component if key[0]==target and key in base_states}
            valid=set(signatures)
            for path in paths:
                observed=json.loads(path.read_bytes())
                states={(e['id'],c['name']):c for e in observed['entities'] for c in e['components']}
                for key in list(valid):
                    state=states.get(key);base=base_states[key]
                    if not state or not all(k in state and k in base for k in ['axis_x','axis_y','axis_z']):valid.remove(key);continue
                    a=np.asarray([base['axis_x'],base['axis_y'],base['axis_z']],float)
                    if abs(np.linalg.det(a))<1e-12:valid.remove(key);continue
                    delta=np.linalg.solve(a,np.asarray([state['axis_x'],state['axis_y'],state['axis_z']],float))
                    shift=np.asarray(state['position_cm'])-np.asarray(base['position_cm'])@delta
                    # Same world rigid transform over EVERY recorded frame proves
                    # that attached decoration and its body are one moving assembly.
                    values=np.concatenate([delta.ravel(),shift]);values=np.round(values,4);values[values==0]=0
                    signatures[key].update(values.tobytes())
            rigid_groups={key:signatures[key].hexdigest() for key in valid}
        assembly_pairs=set()
        # Select genuinely animated components from the complete episode, then
        # inspect every pose of those components, including the closed endpoint.
        animated=set()
        for path in paths:
            frame=json.loads(path.read_bytes())
            states={(e['id'],c['name']):c for e in frame['entities'] for c in e['components']}
            for i in by_actor[target]:
                state=states.get((target,scene.items[i]['component']))
                base=base_states.get((target,scene.items[i]['component']))
                if state and base and i in relative and all(k in state for k in ['axis_x','axis_y','axis_z']):
                    axes=np.asarray([state['axis_x'],state['axis_y'],state['axis_z']],float)
                    base_axes=np.asarray([base['axis_x'],base['axis_y'],base['axis_z']],float)
                    if not np.allclose(axes,base_axes) or not np.allclose(state['position_cm'],base['position_cm']):animated.add(i)
        for path in paths:
            evaluated_frames+=1
            frame=json.loads(path.read_bytes())
            # All recorded frames, not only specially named action steps.
            states={(e['id'],c['name']):c for e in frame['entities'] for c in e['components']}
            transforms={}
            for key,state in states.items():
                base=base_states.get(key)
                if base and all(k in state and k in base for k in ['axis_x','axis_y','axis_z']):
                    axes=np.asarray([state['axis_x'],state['axis_y'],state['axis_z']],float);origin=np.asarray(state['position_cm'],float)
                    if np.allclose(axes,[base['axis_x'],base['axis_y'],base['axis_z']]) and np.allclose(origin,base['position_cm']):continue
                    for i in by_component.get(key,[]):
                        if i in relative:
                            local_axes,local_origin=relative[i]
                            transforms[i]=(local_axes@axes,local_origin@axes+origin)
            for i in by_actor[target]:
                state=states.get((target,scene.items[i]['component']))
                if not state or not state.get('visible',False):continue
                if i not in relative or not all(k in state for k in ['axis_x','axis_y','axis_z']):
                    unresolved.append({'frame':path.name,'instance':list(instance_key(scene.items[i])),'reason':'Missing component basis or per-instance pose'});continue
                t=transforms.get(i,scene.transforms[i]);v=scene.templates[scene.items[i]['mesh']]['vertices'];world=v@t[0]+t[1]
                old=previous.get(i)
                if old is not None:max_step=max(max_step,float(np.linalg.norm(world-old,axis=1).max()))
                previous[i]=world
                if i not in animated:continue
                moving.add(scene.items[i]['component']);samples+=1
                bounds=scene.bounds.copy()
                for j,other in transforms.items():bounds[j]=scene.bounds_at(j,*other)
                low,high=world.min(0),world.max(0)
                near=np.where(np.all(np.minimum(high,bounds[:,1])-np.maximum(low,bounds[:,0])>1e-6,axis=1))[0]
                for j in near:
                    if i==j:continue
                    left_key=(scene.items[i]['actor'],scene.items[i]['component'])
                    right_key=(scene.items[j]['actor'],scene.items[j]['component'])
                    if rigid_assemblies and left_key in rigid_groups and right_key in rigid_groups and rigid_groups[left_key]==rigid_groups[right_key]:
                        assembly_pairs.add((i,int(j)));continue
                    other_state=states.get((scene.items[j]['actor'],scene.items[j]['component']))
                    if other_state and not other_state.get('visible',True):continue
                    result=scene.overlap(i,int(j),tolerance_cm,t,transforms.get(int(j)))
                    row={'frame':path.name,'time':frame['time'],'moving':list(instance_key(scene.items[i])),
                         'obstacle':list(instance_key(scene.items[j])),**result}
                    if result['violates'] is None:unresolved.append(row)
                    elif result['violates']:
                        contacts.append(row)
                        if stop_on_failure:stopped=True;break
                if stopped:break
            if stopped:break
            if previous_time is not None:max_dt=max(max_dt,frame['time']-previous_time)
            previous_time=frame['time']
        results[target]={'rigid_assembly_policy':rigid_assemblies,'rigid_internal_pairs_omitted':len(assembly_pairs),'recorded_frames':len(paths),'evaluated_frames':evaluated_frames,'stopped_after_counterexample':stopped,'moving_pose_samples':samples,'moving_components':sorted(moving),
                         'max_observed_surface_step_cm':max_step,'max_observed_dt_s':max_dt,
                         'sampled_clear':False if contacts else (True if samples and not unresolved else None),
                         'overlaps':contacts,'unresolved':unresolved,'continuous_clearance_certified':False}
    return {'method':'all_required_moving_parts_sampled_solids_v1','targets':results,'total_targets':len(targets),
            'measured_targets':sum(v['sampled_clear'] is not None for v in results.values()),
            'passed_targets':sum(v['sampled_clear'] is True for v in results.values()),'formal_score':None,
            'scope':'Includes same-actor parts and non-pawn-blocking visible obstacles. Instance-local transforms are preserved under component motion; per-instance animation and vertex deformation are unsupported. Discrete observations do not certify continuous clearance.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--geometry',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--episodes',type=Path);p.add_argument('--allowed-contacts',type=Path)
    a=p.parse_args();s=Scene(json.loads(a.geometry.read_bytes()))
    report={'geometry_sha256':digest(a.geometry),'static':static_measure(s,allowed=json.loads(a.allowed_contacts.read_text()) if a.allowed_contacts else [])}
    if a.episodes:report['motion']=motion_measure(s,a.episodes)
    write_json(a.output,report)
    print(json.dumps({k:{n:v for n,v in value.items() if n in ['instance_count','overlap_pair_count','unresolved_pair_count','measured_targets','passed_targets']} for k,value in report.items() if isinstance(value,dict)}))
