"""Visible geometry coverage per required reference region, without candidate names.

Private source object IDs select reference pixels only. Candidate geometry may
use any names or mesh splits. The global silhouette check handles extra geometry;
this check prevents a large correct region from masking a missing smaller one.
"""
import numpy as np


def validate_image_box(box):
    if (not isinstance(box,list) or len(box)!=4 or any(type(v) not in (float,int) for v in box)
            or not np.isfinite(box).all() or not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1)):
        raise ValueError('Image region must be a finite normalized [left, top, right, bottom] box')
    return box


def reference_indices(surface,definition):
    indices=[i for i,name in enumerate(surface['object_names']) if name in definition['objects']]
    if 'image_box' in definition:
        left,top,right,bottom=validate_image_box(definition['image_box'])
        width,height=surface['size']
        if width<=0 or height<=0:raise ValueError('Positive reference sample dimensions required')
        indices=[i for i in indices if left<=(i%width+.5)/width<=right and top<=(i//width+.5)/height<=bottom]
    return indices


def required_regions(candidate,baseline,reference,definitions,tolerance=.03,min_samples=8,minimum_coverage=.8):
    a=candidate['scene'].get('visible_surface',{});b=reference['scene'].get('visible_surface',{})
    if any(v.get('status')!='measured' for v in (a,b)) or a.get('size')!=b.get('size'):
        return {'status':'not_measurable','passed':False,'score':0.,'reason':'Matching native surface samples required'}
    before=baseline['scene']['objects'];objects=candidate['scene']['objects']
    added={name for name,obj in objects.items() if name not in before and obj.get('visible_render') and obj.get('faces',0)>0}
    rows=[]
    for definition in definitions:
        indices=reference_indices(b,definition)
        if len(indices)<min_samples:
            rows.append({'id':definition['id'],'status':'not_measurable','passed':False,'score':0.,
                'reference_samples':len(indices),'reason':'Required region has too few visible reference samples'})
            continue
        points=np.asarray([b['world_points_m'][i] for i in indices],float)
        diagonal=float(np.linalg.norm(np.ptp(points,axis=0)))
        if not np.isfinite(points).all() or diagonal<=1e-8:
            rows.append({'id':definition['id'],'status':'not_measurable','passed':False,'score':0.,
                'reason':'Finite nondegenerate reference region required'})
            continue
        limit=max(diagonal*tolerance,1e-7);matched=[];distances=[]
        for i,point in zip(indices,points):
            name=a['object_names'][i];hit=a['world_points_m'][i]
            if name in added and hit is not None:
                distance=float(np.linalg.norm(np.asarray(hit,float)-point))
                valid=np.isfinite(distance) and distance<=limit
            else:distance=None;valid=False
            matched.append(bool(valid));distances.append(distance if distance is None or np.isfinite(distance) else None)
        fraction=float(np.mean(matched))
        rows.append({'id':definition['id'],'status':'measured','passed':fraction>=minimum_coverage,'score':fraction,
            'reference_samples':len(indices),'matched_samples':sum(matched),'reference_visible_diagonal_m':diagonal,
            'tolerance_m':limit,'pixel_indices':indices,'distance_m':distances})
    measured=bool(rows) and all(r['status']=='measured' for r in rows)
    return {'status':'measured' if measured else 'not_measurable','passed':measured and all(r['passed'] for r in rows),
        'score':float(np.mean([r['score'] for r in rows])) if rows else 0.,'regions':rows,
        'tolerance_fraction':tolerance,'minimum_samples':min_samples,'minimum_coverage':minimum_coverage,
        'candidate_names_used_as_answers':False,'threshold_status':'pilot_not_calibrated',
        'scope':'Each required visible region independently; not hidden part counts, semantics or physical support'}
