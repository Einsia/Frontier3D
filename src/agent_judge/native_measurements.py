"""Read-only native geometry measurements exposed through a small MCP server.

Selectors refer only to hash-bound evaluated geometry. No candidate Python,
model-supplied expressions, arbitrary file access or network operations run.
"""
from __future__ import annotations
import hashlib
import heapq
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from scipy.spatial import cKDTree


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n');temp.replace(path)


def numeric_evidence_pointers(value, pointer='/result'):
    """Enumerate numeric leaves in the saved record, including numeric arrays.

    Tool output presents the result inline, but evidence records wrap it under
    ``result``. Return paths into that record so reviewers need not reconstruct
    the wrapper or mistake an object/list of objects for a numeric observation.
    """
    def numeric(item):
        if type(item) in (int, float):
            return math.isfinite(item)
        return isinstance(item, list) and bool(item) and all(numeric(x) for x in item)

    if numeric(value):
        return [pointer]
    if isinstance(value, dict):
        return [path for key, item in value.items()
                for path in numeric_evidence_pointers(
                    item, pointer + '/' + str(key).replace('~', '~0').replace('/', '~1'))]
    if isinstance(value, list):
        return [path for index, item in enumerate(value)
                for path in numeric_evidence_pointers(item, pointer + '/' + str(index))]
    return []


def triangle_data(vertices,faces):
    xyz=vertices[faces];cross=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);areas=np.linalg.norm(cross,axis=1)/2
    keep=areas>1e-18
    return xyz[keep],areas[keep]


def summary(vertices,faces):
    xyz,area=triangle_data(vertices,faces)
    if not len(xyz):return {'status':'absent','reason':'No nondegenerate triangle surface'}
    points=np.unique(xyz.reshape(-1,3),axis=0);low=points.min(0);high=points.max(0)
    centroid=np.average(xyz.mean(1),axis=0,weights=area)
    centered=points-points.mean(0);_,singular,axes=np.linalg.svd(centered,full_matrices=False)
    projected=points@axes.T
    volume=abs(float(np.einsum('ij,ij->i',xyz[:,0],np.cross(xyz[:,1],xyz[:,2])).sum()/6))
    upper=points[points[:,2]>=high[2]-1e-7].mean(0);lower=points[points[:,2]<=low[2]+1e-7].mean(0)
    return {'status':'measured','triangles':len(xyz),'vertices':len(points),'surface_area_m2':float(area.sum()),
        'bounds_m':[low.tolist(),high.tolist()],'world_span_m':(high-low).tolist(),
        'bounds_center_m':((low+high)/2).tolist(),'surface_centroid_m':centroid.tolist(),
        'top_vertex_centroid_m':upper.tolist(),'bottom_vertex_centroid_m':lower.tolist(),
        'principal_axes':axes.tolist(),'principal_spans_m':np.ptp(projected,axis=0).tolist(),
        'principal_singular_values':singular.tolist(),'principal_axis_note':'Sign is ambiguous; equal singular values make axis orientation ambiguous. Not a fitted transform.',
        'rank':int((singular>1e-7).sum()),'absolute_signed_mesh_volume_m3':volume,
        'volume_note':'Not a cavity capacity or solid-volume certificate; topology and self-intersections need separate checks.'}


class TriangleTree:
    def __init__(self,vertices,faces):
        self.xyz,self.areas=triangle_data(vertices,faces)
        if not len(self.xyz):raise ValueError('Empty surface')
        self.nodes=[];self.low=self.xyz.min(1);self.high=self.xyz.max(1);centers=(self.low+self.high)/2
        def build(ids):
            low,high=self.low[ids].min(0),self.high[ids].max(0);index=len(self.nodes);self.nodes.append(None)
            if len(ids)<=12:self.nodes[index]=(low,high,None,None,ids)
            else:
                axis=np.ptp(centers[ids],axis=0).argmax();middle=len(ids)//2;order=np.argpartition(centers[ids,axis],middle)
                self.nodes[index]=(low,high,build(ids[order[:middle]]),build(ids[order[middle:]]),None)
            return index
        build(np.arange(len(self.xyz)))


def exact_distance(first,second,max_pairs=2_000_000):
    """Exact triangle-feature minimum, with float64 AABB branch-and-bound."""
    try:
        from l2_triangle_contact import triangle_distances
    except ImportError:
        from src.evaluator.l2_triangle_contact import triangle_distances
    def lower(a,b):
        delta=np.maximum(np.maximum(a[0]-b[1],b[0]-a[1]),0)
        return float(np.linalg.norm(delta))
    a=first.xyz.reshape(-1,3);b=second.xyz.reshape(-1,3)
    best=float(cKDTree(a).query(b,workers=1)[0].min());queue=[(lower(first.nodes[0],second.nodes[0]),0,0)];pairs=0
    while queue:
        bound,i,j=heapq.heappop(queue)
        if bound>best+1e-12:continue
        left,right=first.nodes[i],second.nodes[j]
        if left[4] is not None and right[4] is not None:
            pairs+=len(left[4])*len(right[4])
            if pairs>max_pairs:return {'status':'capacity_limited','lower_bound_m':min(bound,queue[0][0] if queue else bound),'upper_bound_m':best,'triangle_pairs':pairs}
            for index in left[4]:
                best=min(best,float(triangle_distances(first.xyz[index],second.xyz[right[4]]).min()))
                if best==0:return {'status':'measured','minimum_surface_distance_m':0.,'triangle_pairs':pairs,'intersect_or_touch':True,'penetration_depth_measured':False}
        elif right[4] is not None or (left[4] is None and np.linalg.norm(left[1]-left[0])>=np.linalg.norm(right[1]-right[0])):
            for child in (left[2],left[3]):heapq.heappush(queue,(lower(first.nodes[child],right),child,j))
        else:
            for child in (right[2],right[3]):heapq.heappush(queue,(lower(left,second.nodes[child]),i,child))
    return {'status':'measured','minimum_surface_distance_m':best,'triangle_pairs':pairs,'intersect_or_touch':best==0,
        'method':'exact triangle intersection, vertex-face and edge-edge distances; no sampled-point substitute',
        'penetration_depth_measured':False}


def clipped_footprint(vertices,faces,z_range=None):
    """Project actual triangles after vertical clipping; retain narrow walls."""
    from shapely.geometry import Polygon,LineString
    from shapely.ops import unary_union
    shapes=[]
    for triangle in vertices[faces]:
        polygon=list(triangle)
        if z_range is not None:
            for height,above in [(z_range[0],True),(z_range[1],False)]:
                clipped=[]
                for i,point in enumerate(polygon):
                    before=polygon[i-1];inside=point[2]>=height if above else point[2]<=height
                    previous=before[2]>=height if above else before[2]<=height
                    if inside!=previous:
                        clipped.append(before+(point-before)*((height-before[2])/(point[2]-before[2])))
                    if inside:clipped.append(point)
                polygon=clipped
                if not polygon:break
        if len(polygon)<2:continue
        xy=np.unique(np.asarray(polygon)[:,:2],axis=0)
        if len(xy)<2:continue
        shape=Polygon(np.asarray(polygon)[:,:2]) if len(polygon)>=3 else LineString(xy)
        if shape.is_empty:continue
        if not shape.is_valid or shape.area<1e-16:shape=LineString(xy)
        shapes.append(shape)
    return unary_union(shapes)


def route_probe(floor,obstacles,points,width,z_range):
    """Continuous swept-disc clearance along a declared polyline, no grid gaps."""
    from shapely.geometry import LineString
    line=LineString(np.asarray(points,float)[:,:2]);corridor=line.buffer(width/2,quad_segs=32)
    support=clipped_footprint(*floor)
    objects=[];minimum=None
    for index,mesh in obstacles:
        footprint=clipped_footprint(*mesh,z_range)
        if footprint.is_empty:continue
        distance=float(line.distance(footprint));minimum=distance if minimum is None else min(minimum,distance)
        if distance<width/2:objects.append({'index':index,'axis_distance_m':distance,'overlap_area_m2':float(corridor.intersection(footprint).area)})
    return {'method':'actual vertically clipped triangle footprints and a continuous polyline disc sweep',
        'path_world_m':points,'requested_width_m':width,'height_range_m':z_range,
        'route_length_m':float(line.length),'unsupported_swept_area_m2':float(corridor.difference(support).area),
        'minimum_axis_to_obstacle_distance_m':minimum,'centered_clear_width_m':2*minimum if minimum is not None else None,
        'obstructions':objects,'obstruction_count':len(objects),'other_routes_searched':False,
        'scope':'Only this bound route and stated height interval; a failed probe does not rule out another route. Semantic endpoint coverage needs separate review.'}


class Measurements:
    def __init__(self,config):
        self.config=config;catalogue=Path(config['catalogue']['path'])
        if sha(catalogue)!=config['catalogue']['sha256']:raise ValueError('Native catalogue changed')
        self.catalogue=json.loads(catalogue.read_text())
        self.objects=[o for o in self.catalogue['snapshots'][0]['objects'] if o.get('geometry')]
        self.source_root=catalogue.parent.resolve();self.cache={};self.trees={}
        self.private=Path(config['output']);self.private.mkdir(parents=True,exist_ok=True)
        self.workspace=Path(config['workspace']);self.ledger={'source':config['catalogue'],'calls':[],'sha256':{}}
        self.max_calls=config.get('budget',100)
        write(self.private/'manifest.json',self.ledger)

    def mesh(self,indices):
        indices=tuple(sorted(set(indices)))
        if not indices or len(indices)>1024 or any(type(i) is not int or not 0<=i<len(self.objects) for i in indices):raise ValueError('Invalid native object selector')
        for index in indices:
            item=self.objects[index]['geometry'];path=Path(item['path']).resolve(strict=True)
            if not path.is_relative_to(self.source_root) or sha(path)!=item['sha256']:raise ValueError('Geometry binding changed')
        if indices in self.cache:return self.cache[indices]
        vertices=[];faces=[];offset=0;total=0
        for index in indices:
            item=self.objects[index]['geometry'];path=Path(item['path']).resolve(strict=True)
            if not path.is_relative_to(self.source_root) or sha(path)!=item['sha256']:raise ValueError('Geometry binding changed')
            with np.load(path,allow_pickle=False) as data:
                v,f=data['vertices_m'].copy(),data['triangles'].copy()
            total+=len(f)
            if total>2_000_000:raise ValueError('Measurement capacity: two million triangles per selector')
            vertices.append(v);faces.append(f+offset);offset+=len(v)
        result=np.concatenate(vertices),np.concatenate(faces);self.cache[indices]=result
        return result

    def tree(self,indices):
        key=tuple(sorted(set(indices)))
        if key not in self.trees:self.trees[key]=TriangleTree(*self.mesh(indices))
        return self.trees[key]

    def tools(self):
        group={'type':'array','items':{'type':'integer','minimum':0},'minItems':1,'maxItems':1024}
        base={'type':'object','properties':{'purpose':{'type':'string'},'requirement_ids':{'type':'array','items':{'type':'string'},'minItems':1}},'required':['purpose','requirement_ids'],'additionalProperties':False}
        inspect={**base,'properties':{**base['properties'],'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100},'name_contains':{'type':'string'}}}
        measure={**base,'properties':{**base['properties'],'operation':{'type':'string','enum':['geometry','relations','surface_clearance']},'groups':{'type':'array','items':group,'minItems':1,'maxItems':32},'axis':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3}},'required':[*base['required'],'operation','groups']}
        route={**base,'properties':{**base['properties'],'floor_indices':group,'excluded_indices':{'type':'array','items':{'type':'integer','minimum':0},'maxItems':1024},
            'points_m':{'type':'array','items':{'type':'array','items':{'type':'number'},'minItems':3,'maxItems':3},'minItems':2,'maxItems':100},
            'width_m':{'type':'number','minimum':.001,'maximum':20},'height_range_m':{'type':'array','items':{'type':'number'},'minItems':2,'maxItems':2}},
            'required':[*base['required'],'floor_indices','excluded_indices','points_m','width_m','height_range_m']}
        settings={**base,'properties':{**base['properties'],'section':{'type':'string','enum':['render','lights','cameras','materials']},
            'object_indices':{'type':'array','items':{'type':'integer','minimum':0},'maxItems':16}},'required':[*base['required'],'section']}
        tools=[{'name':'list_native_geometry','description':'List actual evaluated object surfaces with stable numeric IDs and world-metre bounds. Names are hints; verify identity in images.', 'inputSchema':inspect},
            {'name':'measure_native_geometry','description':'Measure actual vertices and triangles: geometry, relative centers/heights/angles, or exact surface minimum distance. Coincident surfaces do not establish penetration depth; report that limit.', 'inputSchema':measure},
            {'name':'measure_native_route','description':'Probe a continuous declared route using projected actual triangle surfaces in an explicit height band. Include every furnishing/protrusion; exclusions must be the evaluated robot or separately justified floor/ceiling. Report endpoint and height-band assumptions.', 'inputSchema':route}]
        tools.append({'name':'inspect_native_settings','description':'Read bound native render/camera/light or selected material-node settings. A stored numeric shader parameter is a fact; names or RGB alone do not prove a unique colour temperature.', 'inputSchema':settings})
        for tool in tools:
            tool['annotations']={'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}
        return tools

    def call(self,name,args):
        if len(self.ledger['calls'])>=self.max_calls:raise ValueError('Measurement call budget exhausted')
        from jsonschema import Draft202012Validator
        tool=next((t for t in self.tools() if t['name']==name),None)
        if tool is None:raise ValueError('Unknown measurement tool')
        Draft202012Validator(tool['inputSchema']).validate(args)
        start=time.monotonic()
        if name=='list_native_geometry':
            rows=[{'index':i,'name':o['object'],'bounds_m':o.get('bounds_m'),'triangles':o.get('triangles'),'parent':o.get('parent')}
                for i,o in enumerate(self.objects) if args.get('name_contains','').lower() in o['object'].lower()]
            offset=args.get('offset',0);limit=args.get('limit',80)
            result={'objects':rows[offset:offset+limit],'total':len(rows),'next_offset':offset+limit if offset+limit<len(rows) else None}
        elif name=='inspect_native_settings':
            snapshot=self.catalogue['snapshots'][0]
            section=args['section']
            if section=='render':result={'render':snapshot['render'],'unit_scale':snapshot['unit_scale'],'unit_system':snapshot['unit_system']}
            elif section in {'lights','cameras'}:
                result={section:[{k:o[k] for k in ['object','type','matrix_world_m','settings','nodes'] if k in o}
                    for o in snapshot['objects'] if o['type']==('LIGHT' if section=='lights' else 'CAMERA')]}
            else:
                indices=args.get('object_indices',[])
                if not indices or any(not 0<=i<len(self.objects) for i in indices):raise ValueError('Select native object IDs for material inspection')
                result={'materials':[{'index':i,'name':self.objects[i]['object'],'materials':self.objects[i].get('materials',[])} for i in indices]}
        elif name=='measure_native_route':
            ignored=set(args['excluded_indices'])|set(args['floor_indices'])
            if any(not 0<=i<len(self.objects) for i in ignored):raise ValueError('Invalid route exclusion')
            if args['height_range_m'][0]>=args['height_range_m'][1]:raise ValueError('Invalid route height interval')
            obstacles=[(i,self.mesh([i])) for i in range(len(self.objects)) if i not in ignored]
            result=route_probe(self.mesh(args['floor_indices']),obstacles,args['points_m'],args['width_m'],args['height_range_m'])
            result['excluded_objects']=[{'index':i,'name':self.objects[i]['object']} for i in sorted(ignored)]
            result['obstacle_objects_checked']=len(obstacles)
        else:
            groups=args['groups'];summaries=[summary(*self.mesh(group)) for group in groups]
            result={'groups':[{'indices':group,'names':[self.objects[i]['object'] for i in group],**info} for group,info in zip(groups,summaries)]}
            result['nondegenerate_group_count']=sum(info['status']=='measured' for info in summaries)
            if args.get('axis') is not None:
                axis=np.asarray(args['axis'],float);norm=np.linalg.norm(axis)
                if not np.isfinite(axis).all() or norm<1e-12:raise ValueError('Finite nonzero projection axis required')
                axis/=norm;result['projection_axis']=axis.tolist()
                result['projection_intervals_m']=[[float(p.min()),float(p.max())] for group in groups for p in [self.mesh(group)[0]@axis]]
            if args['operation'] in {'relations','surface_clearance'}:
                if len(groups)!=2:raise ValueError('Exactly two groups required for a relation')
                a,b=(np.asarray(info['surface_centroid_m']) for info in summaries)
                result['centroid_delta_m']=(b-a).tolist();result['centroid_distance_m']=float(np.linalg.norm(b-a));result['horizontal_centroid_distance_m']=float(np.linalg.norm(b[:2]-a[:2]))
                first,second=(np.asarray(info['bounds_m']) for info in summaries)
                result['world_axis_signed_interval_gaps_m']=np.maximum(second[0]-first[1],first[0]-second[1]).tolist()
                a_axes,b_axes=(np.asarray(info['principal_axes']) for info in summaries)
                result['unsigned_principal_axis_angles_deg']=np.degrees(np.arccos(np.clip(np.abs(a_axes@b_axes.T),0,1))).tolist()
                features=['surface_centroid_m','bounds_center_m','top_vertex_centroid_m','bottom_vertex_centroid_m']
                result['feature_relations']={}
                for first_feature in features:
                    for second_feature in features:
                        delta=np.asarray(summaries[1][second_feature])-np.asarray(summaries[0][first_feature])
                        result['feature_relations'][first_feature+'_to_'+second_feature]={'delta_m':delta.tolist(),'distance_m':float(np.linalg.norm(delta)),'horizontal_distance_m':float(np.linalg.norm(delta[:2]))}
                if args['operation']=='surface_clearance':result['surface_distance']=exact_distance(self.tree(groups[0]),self.tree(groups[1]))
        number=len(self.ledger['calls'])+1;relative=f'candidate/native_measurements/{number:03d}.json'
        record={'tool':name,'arguments':args,'result':result,'seconds':time.monotonic()-start,'source_catalogue_sha256':self.config['catalogue']['sha256']}
        target=self.private/f'{number:03d}.json';write(target,record)
        destination=self.workspace/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():raise ValueError('Measurement evidence destination already exists')
        destination.write_bytes(target.read_bytes());self.ledger['calls'].append({'number':number,'file':relative,'arguments':args,'tool':name})
        self.ledger['sha256'][relative]=sha(target);write(self.private/'manifest.json',self.ledger)
        response={'evidence':relative,**result}
        if name in {'measure_native_geometry','measure_native_route','inspect_native_settings'}:
            response['numeric_evidence_pointers']=numeric_evidence_pointers(result)
            response['evidence_requirement_ids']=args['requirement_ids']
            response['evidence_pointer_note']='Use these JSON pointers in the evidence file above. Choose the field matching the requirement and explain its meaning and unit; availability alone does not establish compliance.'
        return {'content':[{'type':'text','text':json.dumps(response,ensure_ascii=False)}],'isError':False}


def serve(config_path):
    server=Measurements(json.loads(Path(config_path).read_text()))
    for line in sys.stdin:
        request=json.loads(line);method=request.get('method');identifier=request.get('id')
        if identifier is None:continue
        try:
            if method=='initialize':result={'protocolVersion':request.get('params',{}).get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'3dbench-native-measurements','version':'1'}}
            elif method=='tools/list':result={'tools':server.tools()}
            elif method=='tools/call':result=server.call(request['params']['name'],request['params'].get('arguments',{}))
            elif method=='ping':result={}
            else:raise ValueError('Unsupported method')
            response={'jsonrpc':'2.0','id':identifier,'result':result}
        except Exception as error:
            response={'jsonrpc':'2.0','id':identifier,'result':{'content':[{'type':'text','text':type(error).__name__+': '+str(error)[:1000]}],'isError':True}} if method=='tools/call' else {'jsonrpc':'2.0','id':identifier,'error':{'code':-32603,'message':str(error)[:1000]}}
        print(json.dumps(response,ensure_ascii=False),flush=True)

if __name__=='__main__':serve(sys.argv[1])
