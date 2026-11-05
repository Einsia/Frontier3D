"""Published reference-task scale measurements on complete world-space surfaces.

Role annotations select geometry, not semantic answers. Aperture height is an
interior ray measurement; an outer frame bounding box is never an opening.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import ConvexHull, QhullError
from scipy.spatial.distance import cdist

from .l2_case_compare import full_mesh
from .l2_metrics import entities, planar_dimensions
from .metrics import MissingEvidence, _register


def triangles(obj,evidence):
    if obj.get('geometry_evidence',{}).get('status')=='sampled_surface':
        mesh=full_mesh(obj,evidence.get('geometry_root'))
        if mesh is None:raise MissingEvidence('Complete geometry sidecar required for scale measurement')
        vertices,indices=mesh
        if len(indices)>1_000_000:raise MissingEvidence('Scale measurement exceeds the one-million-triangle capacity')
        result=vertices[indices]
    else:result=np.asarray(obj.get('surface_triangles',[]),float)
    if result.ndim!=3 or result.shape[1:]!=(3,3) or not len(result) or not np.isfinite(result).all():
        raise MissingEvidence('Finite complete triangle surface required')
    return result


def groups(evidence,role):
    result=entities(evidence,role)
    if not result:raise MissingEvidence('Missing numerical geometry role: '+role)
    return [(group,np.concatenate([triangles(o,evidence) for _,o in group['members']])) for group in result]


def ray_distances(surface,origin,direction):
    """Double-sided Moller-Trumbore, with all positive intersection distances."""
    origin=np.asarray(origin,float);direction=np.asarray(direction,float)
    e1=surface[:,1]-surface[:,0];e2=surface[:,2]-surface[:,0]
    p=np.cross(direction,e2);det=np.einsum('ij,ij->i',e1,p)
    valid=np.abs(det)>1e-12
    inv=np.divide(1.,det,out=np.zeros_like(det),where=valid)
    offset=origin-surface[:,0];u=np.einsum('ij,ij->i',offset,p)*inv
    q=np.cross(offset,e1);v=q@direction*inv
    t=np.einsum('ij,ij->i',e2,q)*inv
    return np.sort(t[valid & (u>=-1e-8) & (v>=-1e-8) & (u+v<=1+1e-8) & (t>1e-7)])


def floor_height(support,xy,ceiling):
    hit=ray_distances(support,[*xy,ceiling],[0,0,-1])
    if not len(hit):raise MissingEvidence('No actual support surface under numerical anchor')
    return float(ceiling-hit[0])


@_register('l2_reference_height','role support_role expected tolerance')
def surface_height(check,evidence,spec):
    p=check.params;support=np.concatenate([t for _,t in groups(evidence,p['support_role'])]);outcomes=[]
    for group,surface in groups(evidence,p['role']):
        normal=np.cross(surface[:,1]-surface[:,0],surface[:,2]-surface[:,0])
        centers=surface.mean(axis=1)
        near_top=(np.ptp(surface[:,:,2],axis=1)<=p['tolerance']) & (np.abs(normal[:,2])>1e-12)
        near_top &= centers[:,2]>=surface[:,:,2].max()-p['tolerance']
        points=centers[near_top]
        if not len(points):raise MissingEvidence('No measurable top surface in anchor')
        points=points[np.linspace(0,len(points)-1,min(32,len(points)),dtype=int)]
        heights=[]
        for point in points:
            floor=floor_height(support,point[:2],point[2]+1e-5)
            heights.append(float(point[2]-floor))
        outcomes.append({'entity':group['id'],'heights_m':heights,
            'passed':bool(np.all(np.abs(np.asarray(heights)-p['expected'])<=p['tolerance']))})
    return float(all(v['passed'] for v in outcomes)),{'entities':outcomes,'method':'Actual top-surface samples above local support rays'}


@_register('l2_reference_width','role expected tolerance')
def surface_width(check,evidence,spec):
    outcomes=[]
    for group,surface in groups(evidence,check.params['role']):
        width=float(min(planar_dimensions([('surface',{'surface_triangles':surface.tolist()})])))
        outcomes.append({'entity':group['id'],'width_m':width,
            'passed':abs(width-check.params['expected'])<=check.params['tolerance']})
    return float(all(v['passed'] for v in outcomes)),{'entities':outcomes,'method':'Complete horizontal footprint minimum-area box, short side'}


@_register('l2_reference_diameter','role expected tolerance')
def surface_diameter(check,evidence,spec):
    outcomes=[]
    for group,surface in groups(evidence,check.params['role']):
        points=np.unique(surface.reshape(-1,3),axis=0)
        try:points=points[ConvexHull(points).vertices]
        except QhullError:pass
        if len(points)>20000:raise MissingEvidence('Exact diameter exceeds 20,000 hull-point capacity')
        diameter=max(float(cdist(points[i:i+256],points).max()) for i in range(0,len(points),256))
        outcomes.append({'entity':group['id'],'diameter_m':diameter,
            'passed':abs(diameter-check.params['expected'])<=check.params['tolerance']})
    return float(all(v['passed'] for v in outcomes)),{'entities':outcomes,'method':'Maximum complete-surface vertex separation; no hidden sphere topology requirement'}


@_register('l2_reference_storey','lower_role upper_role expected tolerance')
def storey_height(check,evidence,spec):
    p=check.params
    lower=np.concatenate([t for _,t in groups(evidence,p['lower_role'])])
    upper=np.concatenate([t for _,t in groups(evidence,p['upper_role'])])
    values=[]
    for surface in (lower,upper):
        z=surface[:,:,2]
        # Select the upper horizontal surface, not a wall's total height.
        planar=np.ptp(z,axis=1)<=1e-6
        normal=np.cross(surface[:,1]-surface[:,0],surface[:,2]-surface[:,0])
        planar &= np.abs(normal[:,2])>1e-12
        if not planar.any():raise MissingEvidence('Floor datum needs actual horizontal geometry')
        values.append(float(z[planar].max()))
    difference=values[1]-values[0]
    return float(abs(difference-p['expected'])<=p['tolerance']),{'datum_heights_m':values,'storey_height_m':difference,
        'method':'Top surfaces of two consecutive declared floor/facade-level datums; no hidden storey-count requirement'}


@_register('l2_reference_opening','role support_role expected tolerance require_clear_passage')
def opening_height(check,evidence,spec):
    p=check.params;support=np.concatenate([t for _,t in groups(evidence,p['support_role'])]);outcomes=[]
    for group,surface in groups(evidence,p['role']):
        points=surface.reshape(-1,3);xy=points[:,:2]
        # The broad horizontal principal direction is the opening width; the
        # narrow direction is frame depth. Rotation about world Z is arbitrary.
        centered=xy-xy.mean(axis=0);_,axes=np.linalg.eigh(centered.T@centered)
        width_axis=np.array([*axes[:,-1],0.]);depth_axis=np.cross([0,0,1],width_axis)
        horizontal=np.column_stack((points@width_axis,points@depth_axis))
        middle=(horizontal.min(axis=0)+horizontal.max(axis=0))/2
        center=middle[0]*width_axis+middle[1]*depth_axis
        low=float(points[:,2].min());ground=floor_height(support,center[:2],low+p['tolerance']+1e-5)
        origin=center.copy();origin[2]=ground+1e-5
        top=ray_distances(surface,origin,[0,0,1])
        if not len(top):raise MissingEvidence('No interior lintel/arch surface over the nominated opening')
        height=float(top[0]+1e-5)
        middle_point=center.copy();middle_point[2]=ground+height*.5
        left=ray_distances(surface,middle_point,-width_axis);right=ray_distances(surface,middle_point,width_axis)
        if not len(left) or not len(right):raise MissingEvidence('Both real side boundaries of the opening are required')
        width=float(left[0]+right[0]);depth=float(np.ptp(horizontal[:,1]));clear=True
        if p['require_clear_passage']:
            # Check the middle half-width and 10–80% of the opening height
            # through the frame slab. Report this sampled scope explicitly.
            visible=[triangles(o,evidence) for o in evidence['scene']['objects'].values()
                     if o.get('type')=='MESH' and o.get('visible_render')]
            all_surface=np.concatenate(visible)
            for x in np.linspace(-.25,.25,9)*width:
                for z in np.linspace(.1,.8,9)*height:
                    start=center+x*width_axis-depth_axis*(depth/2+1e-4);start[2]=ground+z
                    hits=ray_distances(all_surface,start,depth_axis)
                    if len(hits) and hits[0]<depth+2e-4:clear=False
        outcomes.append({'entity':group['id'],'opening_height_m':height,'opening_width_at_midheight_m':width,
            'clear_passage_samples':clear,'passed':abs(height-p['expected'])<=p['tolerance'] and clear})
    return float(all(v['passed'] for v in outcomes)),{'entities':outcomes,
        'method':'Interior upward ray plus left/right boundary rays; not outer-frame bounds',
        'passage_scope':'81 rays through central opening volume when required; not a complete arbitrary-shape collision proof'}
