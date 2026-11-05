"""Assembly state metrology without fitted rotations, translations or scales."""
import numpy as np
from scipy.special import logsumexp
from .continuous_surface import triangle_areas


def weights(vertices,faces):
    areas=triangle_areas(vertices,faces)
    if not len(areas) or areas.sum()<=0:raise ValueError('Positive-area part required')
    weight=np.bincount(np.asarray(faces).ravel(),weights=np.repeat(areas/3,3),minlength=len(vertices))
    return weight/weight.sum(),areas


def effective(errors,weight):
    errors=np.asarray(errors,float);weight=np.asarray(weight,float)
    usable=weight>0
    if not np.isfinite(errors).all() or (errors<0).any():raise ValueError('Finite nonnegative errors required')
    return max(0.,float(-logsumexp(-errors[usable]*np.log(2),b=weight[usable])/np.log(2)))


def anchors(vertices,weight):
    used=np.flatnonzero(weight>0);v=np.asarray(vertices,float)
    a=int(used[np.argmin(v[used,0])]);delta=v-v[a]
    b=int(used[np.argmax(np.linalg.norm(delta[used],axis=1))]);line=v[b]-v[a]
    norms=np.linalg.norm(np.cross(delta,line),axis=1)
    c=int(used[np.argmax(norms[used])]);normal=np.cross(v[b]-v[a],v[c]-v[a])
    d=int(used[np.argmax(np.abs(delta[used]@normal))])
    return [a,b,c,d]


def shape_and_return(first,middle,last,*,tolerance_m=.0003):
    meshes=[]
    for v,f in (first,middle,last):
        triangle_areas(v,f);meshes.append((np.asarray(v,float),np.asarray(f)))
    v,f=meshes[0];weight,area=weights(v,f)
    if any(w.shape!=v.shape or not np.array_equal(t,f) for w,t in meshes[1:]):
        return {'status':'surface_comparison_required','reason':'Vertex correspondence changed; use explicit object-pose surface comparison'}
    ids=anchors(v,weight);w=meshes[1][0]
    before=np.linalg.norm(v[:,None,:]-v[ids][None,:,:],axis=2)
    after=np.linalg.norm(w[:,None,:]-w[ids][None,:,:],axis=2)
    error=np.maximum(np.abs(before-after)-tolerance_m,0)/tolerance_m
    values=[effective(error[:,i],weight) for i in range(len(ids))]
    a,b,c,d=ids
    determinants=[float(np.dot(x[b]-x[a],np.cross(x[c]-x[a],x[d]-x[a]))) for x in (v,w)]
    scale=float(np.ptp(v[weight>0],axis=0).max());guard=max(1e-27,(scale*1e-8)**3)
    if abs(determinants[0])<=guard:
        return {'status':'surface_comparison_required','reason':'Four stable intrinsic anchors unavailable'}
    orientation=0. if determinants[0]*determinants[1]>0 else None
    # Each vertex must preserve all four intrinsic distances. Using its worst
    # distance avoids granting credit for the trivial zero distance of an
    # anchor to itself. The oriented witness retains reflection changes.
    residual=effective(error.max(1),weight)
    score=2.**-residual if orientation is not None else 0.
    shape={'status':'measured' if score>0 else 'absent','normalized_errors':[-np.log2(score)] if score>0 else [],
        'reason':None if score>0 else 'Required rigid geometry absent','anchor_indices':ids,
        'anchor_effective_errors':values,'oriented_anchor_volumes_m3':determinants,
        'distance_max_change_m':float(np.abs(before-after).max()),'vertices_observed':int((weight>0).sum()),
        'weighting':'one third of each original triangle area per vertex; worst of four intrinsic distances',
        'registration':'none; intrinsic distances only'}
    displacement=np.linalg.norm(meshes[2][0]-v,axis=1)
    restored={'status':'measured','normalized_errors':[effective(np.maximum(displacement-tolerance_m,0)/tolerance_m,weight)],
        'max_world_displacement_m':float(displacement.max()),'vertices_observed':int((weight>0).sum()),
        'registration':'none; direct world coordinates'}
    return {'status':'measured','rigidity':shape,'restoration':restored}


def centroid(mesh):
    vertices,faces=mesh;areas=triangle_areas(vertices,faces)
    return np.average(np.asarray(vertices)[np.asarray(faces)].mean(1),weights=areas,axis=0)


def explosion(first,middle,slots,*,half_scale_m):
    if half_scale_m<=0:raise ValueError('Positive declared separation scale required')
    rows=[]
    for a in range(len(slots)):
        for b in range(a+1,len(slots)):
            left,right=slots[a],slots[b]
            if any(name not in data for name in (left,right) for data in (first,middle)):
                rows.append({'status':'absent','reason':'Required exploded part pair absent','parts':[left,right]});continue
            before=float(np.linalg.norm(centroid(first[left])-centroid(first[right])))
            after=float(np.linalg.norm(centroid(middle[left])-centroid(middle[right])))
            expansion=max(0.,after-before);q=float(-np.expm1(-np.log(2)*expansion/half_scale_m))
            rows.append({'status':'measured' if q>0 else 'absent','reason':None if q>0 else 'No pair separation expansion observed',
                'normalized_errors':[-np.log2(q)] if q>0 else [],'parts':[left,right],
                'centroid_distance_before_m':before,'centroid_distance_exploded_m':after,
                'separation_gain_m':expansion,'half_scale_m':half_scale_m})
    return rows
