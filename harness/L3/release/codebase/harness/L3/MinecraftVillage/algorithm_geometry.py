"""Exact static box-union compaction for dense voxel scenes.

Only mesh-certified axis-aligned boxes belonging to the same stationary actor
are merged. Dynamic contract entities are retained instance-by-instance. Flat
non-blocking decorative sheets have no solid volume and are reported separately.
"""
from collections import Counter,defaultdict
import itertools
import time
import numpy as np

from .protocol import REQUIRED,read_json,write_json,digest
from .scene_geometry import Scene,static_measure,motion_measure
from .support import measure as support_measure
from .physical_scene import physical_scene


def certified_box(mesh):
    """Accept subdivided closed cuboid boundaries, not arbitrary bounding boxes."""
    vertices=np.asarray(mesh['vertices_cm'],float)
    v,inverse=np.unique(vertices,axis=0,return_inverse=True)
    faces=inverse[np.asarray(mesh['indices'],int).reshape(-1,3)]
    lo,hi=v.min(0),v.max(0)
    if np.any(hi-lo<=1e-8):return None
    triangles=v[faces]
    edges=Counter(tuple(sorted((int(a),int(b)))) for face in faces for a,b in zip(face,np.roll(face,-1)))
    if any(n!=2 for n in edges.values()):return None
    areas=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
    if np.any(areas<=1e-12):return None
    assigned=np.zeros(len(faces),int)
    for axis in range(3):
        for side in [lo[axis],hi[axis]]:
            mask=np.all(np.isclose(triangles[:,:,axis],side,atol=1e-7,rtol=0),axis=1)
            assigned+=mask
            if not np.isclose(areas[mask].sum(),np.prod(np.delete(hi-lo,axis)),rtol=1e-7,atol=1e-8):return None
    if not np.all(assigned==1):return None
    # Closed, consistently oriented faces must enclose the full box volume.
    directed=Counter((int(a),int(b)) for face in faces for a,b in zip(face,np.roll(face,-1)))
    if any(directed[(a,b)]!=directed[(b,a)] for a,b in directed):return None
    volume=abs(np.einsum('ij,ij->i',triangles[:,0],np.cross(triangles[:,1],triangles[:,2])).sum()/6)
    if not np.isclose(volume,np.prod(hi-lo),rtol=1e-6):return None
    return lo,hi


def union_boxes(boxes):
    boxes=[np.round(np.asarray(b,float),5) for b in boxes]
    for cycle in range(3):
        count=len(boxes)
        for axis in range(3):
            groups=defaultdict(list);other=[i for i in range(3) if i!=axis]
            for b in boxes:groups[tuple(b[:,other].ravel())].append(b)
            out=[]
            for parts in groups.values():
                parts.sort(key=lambda b:b[0,axis]);current=parts[0].copy()
                for b in parts[1:]:
                    if b[0,axis]<=current[1,axis]+1e-6:current[1,axis]=max(current[1,axis],b[1,axis])
                    else:out.append(current);current=b.copy()
                out.append(current)
            boxes=out
        if len(boxes)==count:break
    return boxes


def unit_cube():
    # Face winding is closed and consistent. Geometry is evaluator-owned.
    return {'vertices_cm':[[-.5,-.5,-.5],[.5,-.5,-.5],[.5,.5,-.5],[-.5,.5,-.5],
                           [-.5,-.5,.5],[.5,-.5,.5],[.5,.5,.5],[-.5,.5,.5]],
            'indices':[0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7]}


def compact(export, protected_entities=None):
    protected_entities=set(REQUIRED if protected_entities is None else protected_entities)
    templates={k:certified_box(m) for k,m in export['meshes'].items()}
    flat={k:np.linalg.matrix_rank(np.asarray(m['vertices_cm'])-np.asarray(m['vertices_cm']).mean(0),tol=1e-6)<3 for k,m in export['meshes'].items()}
    groups=defaultdict(list);originals={};retained=[];sheets=Counter()
    for item in export['instances']:
        template=templates[item['mesh']]
        if flat[item['mesh']] and not item.get('blocks_pawn') and item['actor'] not in protected_entities:
            sheets[item['actor']]+=1
            continue
        axes=np.asarray([item['axis_x'],item['axis_y'],item['axis_z']],float)
        if template is None:
            retained.append(item);continue
        lo,hi=template;origin=np.asarray(item['origin_cm'])
        if not np.allclose(axes,np.diag(np.diag(axes)),atol=1e-7):
            normalized=(hi-lo)[:,None]*axes
            retained.append({**item,'mesh':'evaluator/unit_cube','origin_cm':(((lo+hi)/2)@axes+origin).tolist(),
                'axis_x':normalized[0].tolist(),'axis_y':normalized[1].tolist(),'axis_z':normalized[2].tolist()})
            continue
        a=lo*np.diag(axes)+origin;b=hi*np.diag(axes)+origin;bounds=np.array([np.minimum(a,b),np.maximum(a,b)])
        if item['actor'] in protected_entities:
            # Normalize tessellated cubes for exact SAT but keep instance identity
            # and component-relative pose for motion reconstruction.
            size=bounds[1]-bounds[0]
            retained.append({**item,'mesh':'evaluator/unit_cube','origin_cm':((bounds[0]+bounds[1])/2).tolist(),
                'axis_x':[float(size[0]),0,0],'axis_y':[0,float(size[1]),0],'axis_z':[0,0,float(size[2])]})
            continue
        key=(item['actor'],item.get('role',''),bool(item.get('blocks_pawn')))
        groups[key].append(bounds);originals[key]=item
    merged=[];proof=[]
    for key,boxes in groups.items():
        boxes_out=union_boxes(boxes);original=originals[key]
        for i,b in enumerate(boxes_out):
            size=b[1]-b[0]
            merged.append({**original,'component':'__evaluator_static_union_'+str(int(key[2])), 'instance':i,
                'mesh':'evaluator/unit_cube','origin_cm':((b[0]+b[1])/2).tolist(),
                'axis_x':[float(size[0]),0,0],'axis_y':[0,float(size[1]),0],'axis_z':[0,0,float(size[2])]})
        proof.append({'actor':key[0],'role':key[1],'blocks_pawn':key[2],'input_boxes':len(boxes),'output_boxes':len(boxes_out)})
    result={**export,'meshes':{**export['meshes'],'evaluator/unit_cube':unit_cube()},'instances':retained+merged}
    return result,{'method':'certified_axis_aligned_static_union_v1','input_instances':len(export['instances']),
        'output_instances':len(result['instances']),'groups':proof,'nonblocking_zero_thickness_sheets':dict(sheets),
        'coordinate_rounding_cm':.00001,'dynamic_entities_merged':False,
        'scope':'Solid geometry only; decorative zero-thickness sheets are visual evidence, not rigid-volume physics.'}


def measure(run,trial,output):
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    source=run/'workspace/episodes/views/scene_geometry.json'
    physical,background=physical_scene(read_json(source),trial)
    physical,proof=compact(physical)
    write_json(output/'compaction.json',proof);write_json(output/'background-exclusions.json',background)
    write_json(output/'physical-scene.json',physical)
    print({'stage':'compacted','instances':proof['output_instances'],'seconds':time.monotonic()-started},flush=True)
    scene=Scene(physical)
    static=static_measure(scene)
    print({'stage':'static','overlaps':static['overlap_pair_count'],'seconds':time.monotonic()-started},flush=True)
    motion=motion_measure(scene,run/'workspace/episodes')
    print({'stage':'motion','seconds':time.monotonic()-started},flush=True)
    support=support_measure(physical,maximum_triangles=100_000_000,maximum_pieces=1_000_000,maximum_triangle_pairs=500_000_000)
    result={'geometry_sha256':digest(source),'static':static,'motion':motion,'support':support,
        'compaction_sha256':digest(output/'compaction.json'),'elapsed_seconds':time.monotonic()-started}
    write_json(output/'geometry.json',result)
    return result


if __name__=='__main__':
    import argparse
    from pathlib import Path
    p=argparse.ArgumentParser()
    for key in ['run','trial','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();measure(a.run.resolve(),a.trial.resolve(),a.output.resolve())
