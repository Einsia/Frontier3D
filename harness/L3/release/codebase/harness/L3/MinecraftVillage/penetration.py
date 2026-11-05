"""Sampled solid penetration for mesh-verified cuboids; never an AABB verdict."""
import json,math
from pathlib import Path
import numpy as np
from .protocol import DOORS,write_json,digest


def box_template(mesh):
    v=np.asarray(mesh['vertices_cm'],float);ids=np.asarray(mesh['indices'],int).reshape(-1,3)
    low,high=v.min(0),v.max(0)
    if np.any(high-low<=0):raise ValueError('Degenerate box')
    corners=np.unique(v,axis=0)
    if len(corners)!=8 or not np.all(np.isclose(corners,low)|np.isclose(corners,high)):raise ValueError('Not a cuboid mesh')
    triangles=v[ids];areas=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
    for axis in range(3):
        for side in (low[axis],high[axis]):
            faces=np.all(np.isclose(triangles[:,:,axis],side),axis=1)
            face_triangles=triangles[faces]
            if len(face_triangles)!=2:raise ValueError('Cuboid face requires two complete triangles')
            sets=[{tuple(point) for point in triangle} for triangle in face_triangles];shared=sets[0]&sets[1]
            if len(sets[0]|sets[1])!=4 or len(shared)!=2:raise ValueError('Overlapping/incomplete cuboid face')
            diagonal=np.array(list(shared));other=np.delete(diagonal[0]-diagonal[1],axis)
            if np.any(np.isclose(other,0)):raise ValueError('Cuboid face triangles must share a diagonal')
            if not math.isclose(float(areas[faces].sum()),float(np.prod(np.delete(high-low,axis))),rel_tol=1e-6):raise ValueError('Incomplete cuboid boundary')
    return (low+high)/2,(high-low)/2


def yaw_box_depth(center,half,yaw,centers,halves,bases=None):
    """SAT minimum translation distance for Z-up yaw OBB against cuboids (axis-aligned fast path when bases are omitted)."""
    t=math.radians(yaw);u=np.array([math.cos(t),math.sin(t),0]);v=np.array([-math.sin(t),math.cos(t),0]);z=np.array([0.,0.,1.])
    basis=np.array([u,v,z])
    if bases is not None:
        depths=[]
        for c,h,b in zip(centers,halves,bases):
            axes=np.concatenate([basis,b,np.cross(basis[:,None,:],b[None,:,:]).reshape(-1,3)])
            norms=np.linalg.norm(axes,axis=1);axes=axes[norms>1e-9]/norms[norms>1e-9,None]
            depths.append(float((half@np.abs(basis@axes.T)+h@np.abs(b@axes.T)-np.abs((c-center)@axes.T)).min()))
        return np.array(depths)
    axes=np.array([[1,0,0],[0,1,0],[0,0,1],u,v])
    gaps=half@np.abs(basis@axes.T)+(halves@np.abs(axes.T))-np.abs((centers-center)@axes.T)
    return gaps.min(axis=1)


def evaluate(workspace):
    export=json.loads((workspace/'geometry/geometry.json').read_text());templates={k:box_template(v) for k,v in export['meshes'].items()}
    boxes=[]
    for item in export['instances']:
        if not item['blocks_pawn']:continue
        mid,half=templates[item['mesh']];axes=np.array([item['axis_x'],item['axis_y'],item['axis_z']]);scale=np.linalg.norm(axes,axis=1);rotation=axes/scale[:,None]
        if not np.allclose(rotation@rotation.T,np.eye(3),atol=1e-6):raise ValueError('Sheared cuboid unsupported')
        center=mid@axes+item['origin_cm'];ext=half@np.abs(axes)
        boxes.append((item,center,ext,half*scale,rotation))
    centers=np.array([b[1] for b in boxes]);halves=np.array([b[2] for b in boxes]);result={}
    for target in DOORS:
        folder=workspace/target.replace('.','_');initial=json.loads((folder/'before.json').read_text());e=next(e for e in initial['entities'] if e['id']==target);leaf=next(c for c in e['components'] if c['name'] in ['DoorLeaf','GateLeaf'])
        base=next(i for i in export['instances'] if i['actor']==target and i['component']==leaf['name']);mid,half=templates[base['mesh']];half=half*np.linalg.norm([base['axis_x'],base['axis_y'],base['axis_z']],axis=1)
        if not np.allclose(mid,0):raise ValueError('Observer component origin must equal cuboid center')
        ids=np.array([i for i,b in enumerate(boxes) if b[0]['actor']!=target]);rows=[];samples=0
        for path in sorted(folder.glob('trajectory_*.json')):
            f=json.loads(path.read_text())
            if f.get('active_step') not in {'action_1','motion_wait_1','motion_view_1','wait_1','action_2','wait_2','action_3','wait_3'}:continue
            e=next(e for e in f['entities'] if e['id']==target);c=next(c for c in e['components'] if c['name']==leaf['name']);roll,pitch,yaw=c['rotation_deg']
            if abs(roll)+abs(pitch)>1e-6:raise ValueError('Unsupported tilted door')
            center=np.array(c['position_cm']);near=ids[np.all(np.abs(centers[ids]-center)<=halves[ids]+np.linalg.norm(half)+2,axis=1)]
            depth=yaw_box_depth(center,half,yaw,centers[near],np.array([boxes[i][3] for i in near]),np.array([boxes[i][4] for i in near]));samples+=1
            for i,d in zip(near,depth):
                if d>2+1e-6:rows.append({'time':f['time'],'step':f['active_step'],'actor':boxes[i][0]['actor'],'component':boxes[i][0]['component'],'instance':boxes[i][0]['index'] if 'index' in boxes[i][0] else boxes[i][0].get('instance'),'minimum_translation_cm':float(d),'yaw':yaw,'frame':path.name})
        result[target]={'sample_count':samples,'passed':not rows,'max_penetration_cm':max((x['minimum_translation_cm'] for x in rows),default=0),'contacts':rows}
    output={'method':'mesh-verified-cuboid-SAT-v1','tolerance_cm':2,'geometry_sha256':digest(workspace/'geometry/geometry.json'),'doors':result,'passed':sum(v['passed'] for v in result.values()),'total':len(result),'scope':'Door/gate solid leaves against external visible pawn-blocking static cuboids at recorded poses; not continuous collision or full scene certification','formal_score_eligible':False}
    write_json(workspace.parent/'metrics/door_penetration.json',output)
    return output

if __name__=='__main__':
 import sys
 r=evaluate(Path(sys.argv[1]));print({k:{n:v[n] for n in ['sample_count','passed','max_penetration_cm']} for k,v in r['doors'].items()})
