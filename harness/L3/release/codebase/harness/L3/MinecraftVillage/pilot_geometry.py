"""Adapt actual UE mesh instances to L2's complete-surface support measurement."""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import numpy as np
from PIL import Image
from src.evaluator.l2_physical import physical_plausibility, DEFAULT_POLICY
from src.evaluator.l2_reference_image import appearance_components
from src.evaluator.l2_reference_boxes import pair_metrics
from scipy.optimize import linear_sum_assignment
from .protocol import digest,write_json


def world_geometry(export):
    templates={}
    for key,m in export['meshes'].items():
        vertices=np.asarray(m['vertices_cm'],float);indices=np.asarray(m['indices'],int).reshape(-1,3)
        templates[key]=(vertices,indices)
    groups={}
    for i in export['instances']:
        v,indices=templates[i['mesh']]
        axes=np.array([i['axis_x'],i['axis_y'],i['axis_z']])
        world=(v@axes+np.asarray(i['origin_cm']))/100
        groups.setdefault(i['actor'],[]).append(world[indices])
    return {name:np.concatenate(parts) for name,parts in groups.items()}


def projected_box(surface,position,target,width,height):
    forward=np.asarray(target)-np.asarray(position);forward=forward/np.linalg.norm(forward)
    right=np.cross([0,0,1],forward);right=right/np.linalg.norm(right)
    up=np.cross(forward,right)
    p=surface.reshape(-1,3)*100-np.asarray(position)
    depth=p@forward
    if np.any(depth<=0):return None
    x=.5+.5*(p@right)/depth
    y=.5-.5*(p@up)/depth*(width/height)
    return np.clip([x.min(),y.min(),x.max(),y.max()],0,1).tolist()


def main():
    p=argparse.ArgumentParser();p.add_argument('--geometry',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--bindings',type=Path,required=True);p.add_argument('--annotations',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    exported=json.loads(a.geometry.read_text());groups=world_geometry(exported)
    print(json.dumps({'actors':len(groups),'instances':len(exported['instances']),'triangles':sum(len(v) for v in groups.values())}),flush=True)
    evidence={'scene':{'objects':{name:{'type':'MESH','visible_render':True,'surface_triangles':v.tolist()} for name,v in groups.items()}}}
    start=time.monotonic();
    import src.evaluator.l2_physical as l2
    from .contact import contact
    original_contact=l2.contact
    try:
        l2.contact=contact
        support=physical_plausibility(evidence,dict(DEFAULT_POLICY))
    finally:l2.contact=original_contact
    support.update(elapsed_seconds=time.monotonic()-start,geometry_sha256=digest(a.geometry),unit_conversion='UE centimeters to meters')
    write_json(a.output/'support.json',support);print('support complete',flush=True)
    left,right=[np.asarray(Image.open(x).convert('RGB'),float)/255 for x in [a.reference,a.candidate]]
    appearance=appearance_components(left,right)
    appearance.update(reference_sha256=digest(a.reference),candidate_sha256=digest(a.candidate),
        camera_status='Candidate public overview camera, not fitted to reference; projection differences affect this appearance proxy')
    write_json(a.output/'appearance.json',appearance);print('appearance complete',flush=True)
    annotations=json.loads(a.annotations.read_text());assert annotations['reference_sha256']==digest(a.reference)
    view=json.loads(a.bindings.read_text())['views']['overview']
    h,w=left.shape[:2]
    candidates=[{'id':k,'box':projected_box(v,view['position_cm'],view['look_cm'],w,h)} for k,v in groups.items() if k.startswith('building.')]
    refs=annotations['buildings'];matrix=np.array([[pair_metrics(r['box'],c['box'],[w,h])['score'] for c in candidates] for r in refs])
    rows,cols=linear_sum_assignment(-matrix);matches={int(i):int(j) for i,j in zip(rows,cols)}
    details=[]
    for i,r in enumerate(refs):
        j=matches.get(i);c=candidates[j] if j is not None else None
        details.append({'reference':r,'candidate':c,'metrics':pair_metrics(r['box'],c['box'],[w,h]) if c else {'score':0.}})
    score=sum(x['metrics']['score'] for x in details)/len(refs)*len(refs)/max(len(refs),len(candidates))
    write_json(a.output/'building_localization.json',{'method':'L2 pair_metrics + Hungarian matching',
        'score':score,'reference_count':len(refs),'candidate_count':len(candidates),'matches':details,
        'annotations_sha256':digest(a.annotations),'source':'assistant-reviewed reference boxes and engine-projected candidate mesh bounds',
        'formal_score_eligible':False,'scope':'Visible-building 2D location/size proxy; not semantic geometry correctness',
        'limitations':['Reference annotations have not been independently human validated.',
                       'Candidate camera is not reference-calibrated.',
                       'Projected bounds do not account for occlusion; building identity is checked separately by visual review.']})
    print('localization complete',flush=True)

if __name__=='__main__':main()
