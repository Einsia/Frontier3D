"""Visible edit-surface thickness probes on complete evaluated geometry.

No hidden reference thickness is demanded. Reference rays only select visible
surface locations at which a back surface exists. Candidates must have a real,
oppositely facing back surface at nonzero depth, regardless of mesh splitting.
This is a local sampled test, not a watertightness or complete support proof.
"""
import numpy as np

from .l2_reference_numeric import triangles
from .metrics import MissingEvidence


def exit_surface(surface,point,normal,epsilon):
    direction=-np.asarray(normal,float);direction/=max(np.linalg.norm(direction),1e-12)
    origin=np.asarray(point,float)+direction*epsilon
    e1=surface[:,1]-surface[:,0];e2=surface[:,2]-surface[:,0]
    p=np.cross(direction,e2);det=np.einsum('ij,ij->i',e1,p)
    valid=np.abs(det)>1e-12;inverse=np.divide(1.,det,out=np.zeros_like(det),where=valid)
    offset=origin-surface[:,0];u=np.einsum('ij,ij->i',offset,p)*inverse
    q=np.cross(offset,e1);v=q@direction*inverse;t=np.einsum('ij,ij->i',e2,q)*inverse
    hits=valid&(u>=-1e-8)&(v>=-1e-8)&(u+v<=1+1e-8)&(t>epsilon)
    if not hits.any():return None
    indices=np.flatnonzero(hits);index=indices[np.argmin(t[hits])]
    # A true back boundary faces outwards along the inward travel direction.
    outward=float(np.dot(np.cross(e1[index],e2[index]),direction))>1e-12
    return float(t[index]+epsilon) if outward else None


def visible_thickness(candidate,baseline,reference,targets,max_samples=48):
    before=baseline['scene']['objects'];a=candidate['scene'].get('visible_surface',{});b=reference['scene'].get('visible_surface',{})
    if any(s.get('status')!='measured' for s in (a,b)) or a.get('size')!=b.get('size'):
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Matching native surface samples required'}
    reference_meshes=[triangles(o,reference) for name,o in reference['scene']['objects'].items() if name in targets and o.get('faces',0)>0]
    candidate_meshes=[triangles(o,candidate) for name,o in candidate['scene']['objects'].items() if name not in before and o.get('faces',0)>0 and o.get('visible_render')]
    if not reference_meshes or not candidate_meshes:
        return {'status':'missing','passed':False,'score':0.,'reason':'Complete reference and added target surfaces required'}
    ref=np.concatenate(reference_meshes);new=np.concatenate(candidate_meshes)
    if max(len(ref),len(new))>500000:raise MissingEvidence('Thickness probe capacity is 500,000 triangles; no sampled fallback')
    locations=[i for i,name in enumerate(b['object_names']) if name in targets]
    if not locations:return {'status':'not_measurable','passed':False,'score':0.,'reason':'Reference target is not visible'}
    locations=np.asarray(locations)[np.linspace(0,len(locations)-1,min(max_samples,len(locations)),dtype=int)]
    diagonal=float(np.linalg.norm(np.ptp(ref.reshape(-1,3),axis=0)))
    epsilon=max(diagonal*1e-7,1e-7);probes=[]
    for i in locations:
        if exit_surface(ref,b['world_points_m'][i],b['normals'][i],epsilon) is None:continue
        name=a['object_names'][i];thickness=None
        if name is not None and name not in before:
            thickness=exit_surface(new,a['world_points_m'][i],a['normals'][i],epsilon)
        probes.append({'pixel_index':int(i),'has_back_surface':thickness is not None,'candidate_ray_depth_m':thickness})
    if len(probes)<4:
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Fewer than four observable reference thickness probes','probes':probes}
    fraction=sum(p['has_back_surface'] for p in probes)/len(probes)
    return {'status':'measured','passed':fraction>=.9,'score':fraction,'probes':probes,'numerical_epsilon_m':epsilon,
        'reference_hidden_thickness_required':False,'threshold_status':'pilot_not_calibrated',
        'scope':'Local nonzero back-surface evidence at visible target points; not global solidity, cavity, or support certification'}


def measure_structure(candidate, baseline, reference, targets, definition):
    """A failed or unobservable structural method cannot turn into a passing gate."""
    from .l2_edit_cavity import open_cavity
    methods = {'visible_target_thickness': visible_thickness}
    if definition['open_cavity']:
        methods['open_target_cavity'] = open_cavity
    result = {}
    for name, measure in methods.items():
        try:
            result[name] = measure(candidate, baseline, reference, targets)
        except MissingEvidence as error:
            result[name] = {'status': 'not_measurable', 'passed': False, 'score': 0., 'reason': str(error)}
    return result
