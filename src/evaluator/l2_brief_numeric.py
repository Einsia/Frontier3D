"""Brief numerical measurements on complete evaluated world-space geometry.

Public role/parent bindings select geometry; they do not classify its semantics.
No private example dimensions, names or images are used.
"""
import hashlib

import numpy as np
from scipy.spatial import ConvexHull,QhullError
from scipy.spatial.distance import cdist

from .l2_reference_numeric import groups,triangles,ray_distances
from .metrics import MissingEvidence,_register


def span_xy(points):
    xy=np.unique(np.asarray(points)[:,:2],axis=0)
    if len(xy)<3:raise MissingEvidence('A finite two-dimensional footprint is required')
    try:hull=xy[ConvexHull(xy).vertices]
    except QhullError:raise MissingEvidence('Degenerate footprint') from None
    edges=np.roll(hull,-1,axis=0)-hull;best=None
    for angle in np.unique(np.arctan2(edges[:,1],edges[:,0])%(np.pi/2)):
        c,s=np.cos(angle),np.sin(angle);extent=np.ptp(hull@np.array([[c,-s],[s,c]]),axis=0)
        if best is None or np.prod(extent)<np.prod(best):best=extent
    return np.sort(best)


def interval(value,low,high,tolerance):
    return bool((low is None or value>=low-abs(low)*tolerance-1e-8)
        and (high is None or value<=high+abs(high)*tolerance+1e-8))


def floor_at(surface,xy,ceiling):
    distances=ray_distances(surface,[*xy,ceiling],[0,0,-1])
    if not len(distances):raise MissingEvidence('No actual local support surface below the measurement location')
    return float(ceiling-distances[0])


@_register('l2_brief_count','role minimum','maximum')
def entity_count(check,evidence,spec):
    selected=groups(evidence,check.params['role']);seen={};duplicates=[]
    for group,surface in selected:
        area=np.linalg.norm(np.cross(surface[:,1]-surface[:,0],surface[:,2]-surface[:,0]),axis=1).sum()/2
        if area<=1e-12:raise MissingEvidence('A countable entity needs real, nondegenerate surface geometry')
        # Reject identical co-located copies, independent of mesh splitting and
        # triangle order. This does not claim semantic entity recognition.
        points=np.unique(np.round(surface.reshape(-1,3),8),axis=0);points[points==0]=0
        key=hashlib.sha256(points.tobytes()).hexdigest()
        if key in seen:duplicates.append([seen[key],group['id']])
        seen[key]=group['id']
    count=len(selected);p=check.params
    return float(p['minimum']<=count<=p.get('maximum',100000) and not duplicates),{
        'role':p['role'],'measured_entities':count,'entity_ids':[g['id'] for g,_ in selected],
        'duplicate_geometry':duplicates,'selection':'Actual role-bound mesh groups, not object-name or semantic classification'}


@_register('l2_brief_dimensions','role scope lower upper relative_tolerance')
def dimensions(check,evidence,spec):
    p=check.params;selected=groups(evidence,p['role'])
    if p['scope']=='union':selected=[({'id':'role union'},np.concatenate([s for _,s in selected]))]
    elif p['scope']!='each':raise ValueError('Dimension scope must be each or union')
    rows=[]
    for group,surface in selected:
        points=surface.reshape(-1,3);values=[*map(float,span_xy(points)),float(np.ptp(points[:,2]))]
        rows.append({'entity':group['id'],'dimensions_m':values,
            'passed':all(interval(v,lo,hi,p['relative_tolerance']) for v,lo,hi in zip(values,p['lower'],p['upper']))})
    return float(all(r['passed'] for r in rows)),{'axes':['horizontal_short','horizontal_long','vertical_span'],
        'entities':rows,'method':'Complete evaluated points; minimum-area horizontal footprint, invariant to Z rotation'}


@_register('l2_brief_level','role support_role endpoint lower upper relative_tolerance')
def relative_level(check,evidence,spec):
    p=check.params;support=np.concatenate([s for _,s in groups(evidence,p['support_role'])]);rows=[]
    for group,surface in groups(evidence,p['role']):
        points=np.unique(surface.reshape(-1,3),axis=0)
        extremum=points[:,2].max() if p['endpoint']=='top' else points[:,2].min()
        selected=points[np.abs(points[:,2]-extremum)<=1e-6]
        if len(selected)>256:raise MissingEvidence('More than 256 extreme support points; no sampled fallback')
        ceiling=max(float(support[:,:,2].max()),float(points[:,2].max()))+1.
        values=[float(v[2]-floor_at(support,v[:2],ceiling)) for v in selected]
        rows.append({'entity':group['id'],'heights_above_local_support_m':values,
            'passed':all(interval(v,p['lower'],p['upper'],p['relative_tolerance']) for v in values)})
    return float(all(r['passed'] for r in rows)),{'entities':rows,
        'scope':'All extreme-height vertices against local support rays; not complete contact or stability certification'}


@_register('l2_brief_camera_ground','camera support_role lower upper relative_tolerance')
def camera_ground(check,evidence,spec):
    p=check.params;camera=evidence['scene'].get('cameras',{}).get(p['camera'])
    if not camera:raise MissingEvidence('A pixel-matched saved camera is required')
    point=np.asarray(camera['location'],float)
    support=np.concatenate([s for _,s in groups(evidence,p['support_role'])])
    height=float(point[2]-floor_at(support,point[:2],point[2]+1e-6))
    return float(interval(height,p['lower'],p['upper'],p['relative_tolerance'])),{'height_above_local_ground_m':height,
        'ground_height_m':float(point[2]-height),'camera':p['camera']}


@_register('l2_brief_waterline','hull_role deck_role water_role')
def waterline(check,evidence,spec):
    p=check.params;water=np.concatenate([s for _,s in groups(evidence,p['water_role'])]);rows=[]
    for role in (p['hull_role'],p['deck_role']):
        for group,surface in groups(evidence,role):
            points=surface.reshape(-1,3);xy=(points[:,:2].min(axis=0)+points[:,:2].max(axis=0))/2
            water_z=floor_at(water,xy,max(float(points[:,2].max()),float(water[:,:,2].max()))+1.)
            low,high=float(points[:,2].min()-water_z),float(points[:,2].max()-water_z)
            passed=low<-1e-6 and high>1e-6 if role==p['hull_role'] else low>1e-6
            rows.append({'entity':group['id'],'role':role,'bottom_above_water_m':low,'top_above_water_m':high,'passed':passed})
    return float(all(r['passed'] for r in rows)),{'entities':rows,'scope':'Local water-plane crossing and deck clearance, not vessel semantics or buoyancy'}


@_register('l2_brief_diameter_range','role lower upper relative_tolerance require_endpoints')
def diameter_range(check,evidence,spec):
    p=check.params;rows=[]
    for group,surface in groups(evidence,p['role']):
        points=np.unique(surface.reshape(-1,3),axis=0)
        try:points=points[ConvexHull(points).vertices]
        except QhullError:pass
        if len(points)>20000:raise MissingEvidence('Diameter exceeds 20,000 hull-point capacity')
        diameter=max(float(cdist(points[i:i+256],points).max()) for i in range(0,len(points),256))
        rows.append({'entity':group['id'],'diameter_m':diameter,'passed':interval(diameter,p['lower'],p['upper'],p['relative_tolerance'])})
    values=[r['diameter_m'] for r in rows]
    spans=(not p['require_endpoints'] or (interval(min(values),p['lower'],p['lower'],p['relative_tolerance'])
        and interval(max(values),p['upper'],p['upper'],p['relative_tolerance'])))
    return float(all(r['passed'] for r in rows) and spans),{'entities':rows,'range_endpoints_present':spans,
        'method':'Exact complete-surface maximum Euclidean vertex separation'}


def validate(check):
    p=check.params
    for key in ('role','support_role','camera','hull_role','deck_role','water_role'):
        if key in p and (not isinstance(p[key],str) or not p[key]):raise ValueError('Nonempty geometry selector required')
    if 'relative_tolerance' in p and (type(p['relative_tolerance']) not in (int,float)
            or not np.isfinite(p['relative_tolerance']) or not 0<=p['relative_tolerance']<=.5):raise ValueError('Invalid numerical tolerance')
    if check.metric=='l2_brief_count':
        if any(type(p[k]) is not int or p[k]<1 for k in ('minimum','maximum') if k in p):raise ValueError('Positive integer counts required')
        if p.get('maximum',100000)<p['minimum']:raise ValueError('Reversed count range')
    if check.metric=='l2_brief_dimensions':
        if p['scope'] not in {'union','each'}:raise ValueError('Unknown dimension scope')
        if not all(isinstance(p[k],list) and len(p[k])==3 for k in ('lower','upper')):raise ValueError('Three dimension bounds required')
        bounds=zip(p['lower'],p['upper'])
    else:bounds=[(p.get('lower'),p.get('upper'))] if 'lower' in p else []
    for lower,upper in bounds:
        for value in (lower,upper):
            if value is not None and (type(value) not in (int,float) or not np.isfinite(value)):raise ValueError('Finite numerical bounds required')
        if lower is not None and upper is not None and lower>upper:raise ValueError('Reversed numerical interval')
    if 'endpoint' in p and p['endpoint'] not in {'top','bottom'}:raise ValueError('Unknown surface endpoint')
    if 'require_endpoints' in p and type(p['require_endpoints']) is not bool:raise ValueError('Boolean endpoint policy required')
    if check.metric=='l2_brief_route':
        for key in ('road_role','start_role','goal_role'):
            if not isinstance(p[key],str) or not p[key]:raise ValueError('Nonempty route selector required')
        for key in ('min_width','cell_size','max_snap','clearance_height','surface_epsilon','max_step','max_slope'):
            if type(p[key]) not in (int,float) or not np.isfinite(p[key]) or p[key]<=0:raise ValueError('Positive finite route parameters required')
        if p['cell_size']>p['min_width']/4:raise ValueError('Route resolution cannot resolve the requested width')
        if 'clearance_roles' in p and (not isinstance(p['clearance_roles'],list) or not p['clearance_roles']
                or any(not isinstance(v,str) or not v for v in p['clearance_roles'])):raise ValueError('Nonempty clearance role list required')
    if check.metric=='l2_brief_opening':
        if p['passage_shape'] not in {'rectangle','ball'}:raise ValueError('Unknown passage section')
        for key in ('min_width','min_height'):
            if key=='min_height' and p[key] is None:continue
            if type(p[key]) not in (int,float) or not np.isfinite(p[key]) or p[key]<=0:raise ValueError('Positive opening dimensions required')
