"""Continuous geometric motion observations in unchanged world coordinates.

Distances to four intrinsic witnesses measure rigid shape independently of pose.
Joint and hinge functions consume observed geometric landmarks; callers must
bind their semantic annotations and correspondence before aggregation.
"""
import numpy as np
from .continuous_assembly_state import weights,anchors,effective
from .continuous_surface import triangle_areas


def error_row(distance,half_scale_m,precision_m=1e-7,**metadata):
    values=np.asarray(distance,float)
    if not values.size or not np.isfinite(values).all() or (values<0).any():raise ValueError('Nonempty finite nonnegative motion errors required')
    if not np.isfinite([half_scale_m,precision_m]).all() or half_scale_m<=0 or precision_m<0:
        raise ValueError('Positive motion half-scale and nonnegative precision required')
    return {'status':'measured','normalized_errors':(np.maximum(values-precision_m,0)/half_scale_m).reshape(-1).tolist(),
            'distance_errors_m':values.reshape(-1).tolist(),'half_scale_m':half_scale_m,
            'numeric_precision_m':precision_m,'registration':'none',**metadata}


def rigidity(meshes,frames,*,half_scale_m=.005,precision_m=1e-7):
    if len(meshes)!=len(frames) or len(meshes)<2:raise ValueError('Complete motion sequence required')
    v,f=np.asarray(meshes[0][0],float),np.asarray(meshes[0][1]);weight,_=weights(v,f)
    ids=anchors(v,weight);base=np.linalg.norm(v[:,None,:]-v[ids][None,:,:],axis=2)
    a,b,c,d=ids;initial=float(np.dot(v[b]-v[a],np.cross(v[c]-v[a],v[d]-v[a])))
    span=float(np.ptp(v[weight>0],axis=0).max());guard=max(1e-27,(span*1e-8)**3)
    if abs(initial)<=guard:
        return {'status':'technical_failure','reason':'Rigid motion needs stable intrinsic witnesses or a pose-bound surface fallback'}
    worst=np.zeros(len(v));observations=[];reversed_orientation=False
    for frame,(vertices,faces) in zip(frames,meshes):
        w,t=np.asarray(vertices,float),np.asarray(faces);triangle_areas(w,t)
        if w.shape!=v.shape or not np.array_equal(t,f):
            return {'status':'technical_failure','reason':'Motion vertex correspondence changed; pose-bound surface fallback required','frame':frame}
        residual=np.abs(np.linalg.norm(w[:,None,:]-w[ids][None,:,:],axis=2)-base).max(1)
        determinant=float(np.dot(w[b]-w[a],np.cross(w[c]-w[a],w[d]-w[a])))
        reversed_orientation|=determinant*initial<=0
        worst=np.maximum(worst,residual)
        observations.append({'frame':frame,'maximum_intrinsic_distance_error_m':float(residual.max()),
                             'oriented_witness_volume_m3':determinant})
    row=error_row(worst,half_scale_m,precision_m)
    normalized=effective(row['normalized_errors'],weight)
    return {**row,'normalized_errors':[normalized] if not reversed_orientation else [],
        'status':'absent' if reversed_orientation else 'measured',
        'reason':'Rigid orientation reversed or collapsed' if reversed_orientation else None,
        'frames':list(frames),'anchor_indices':ids,'observations':observations,
        'maximum_intrinsic_distance_error_m':float(worst.max()),
        'temporal_aggregation':'worst per vertex across all required frames',
        'spatial_aggregation':'original triangle-area weighted vertices, worst of four witness distances'}


def attachment(endpoints,attachments,*,half_scale_m=.01,precision_m=1e-7):
    a,b=np.asarray(endpoints,float),np.asarray(attachments,float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3 or not len(a):raise ValueError('Corresponding joint trajectories required')
    distances=np.linalg.norm(a-b,axis=1)
    return error_row([float(distances.max())],half_scale_m,precision_m,
        per_frame_joint_gap_m=distances.tolist(),temporal_aggregation='maximum observed attachment gap')


def coaxial_slide(outer,inner,*,half_scale_m=.01,precision_m=1e-7):
    outer,inner=np.asarray(outer,float),np.asarray(inner,float)
    if outer.shape!=inner.shape or outer.ndim!=3 or outer.shape[1:]!=(2,3) or not len(outer):
        raise ValueError('Corresponding observed two-ended strut axes required')
    direction=outer[:,1]-outer[:,0];length=np.linalg.norm(direction,axis=1)
    if not np.isfinite(outer).all() or not np.isfinite(inner).all():raise ValueError('Finite observed strut axes required')
    if (length<=0).any() or (np.linalg.norm(inner[:,1]-inner[:,0],axis=1)<=0).any():
        return {key:{'status':'absent','reason':'Required finite strut axis absent'} for key in ('alignment','nesting','sliding')}
    unit=direction/length[:,None];offset=inner-outer[:,None,0]
    coordinates=np.einsum('nkj,nj->nk',offset,unit)
    perpendicular=np.linalg.norm(offset-coordinates[:,:,None]*unit[:,None,:],axis=2)
    lower,upper=coordinates.min(1),coordinates.max(1)
    gaps=np.maximum(np.maximum(lower-length,-upper),0.)
    # Use the two centres. Referencing only the barrel's lower end would
    # mistake symmetric barrel stretching for relative piston translation.
    offsets=coordinates.mean(1)-length/2
    excursion=float(np.ptp(offsets));slide=float(-np.expm1(-np.log(2)*excursion/half_scale_m))
    return {'alignment':error_row([float(perpendicular.max())],half_scale_m,precision_m,
                                 per_frame_axis_distance_m=perpendicular.tolist()),
        'nesting':error_row([float(gaps.max())],half_scale_m,precision_m,
                           per_frame_axial_separation_m=gaps.tolist()),
        'sliding':{'status':'measured' if slide>0 else 'absent','normalized_errors':[-float(np.log2(slide))] if slide>0 else [],
                   'reason':None if slide>0 else 'No relative axial sliding observed',
                   'relative_centroid_coordinates_m':offsets.tolist(),'excursion_m':excursion,'half_scale_m':half_scale_m,
                   'definition':'1 - 2 ** (-observed relative axial excursion / half_scale)', 'registration':'none'}}


def hinge_invariants(points,axis,*,half_scale_m=.01,precision_m=1e-7):
    """Check a bound door landmark population rotates about the observed hinge.

    Axial position, radius and relative angular phase must be preserved. A
    common rotation around this particular observed axis is a feature property;
    candidate geometry is never transformed or registered to a reference.
    """
    points,axis=np.asarray(points,float),np.asarray(axis,float)
    if points.ndim!=3 or points.shape[2]!=3 or not points.shape[0] or not points.shape[1] or axis.shape!=(2,3):
        raise ValueError('Nonempty door landmarks and fixed hinge endpoints required')
    direction=axis[1]-axis[0];length=float(np.linalg.norm(direction))
    if length<=0:return {'status':'absent','reason':'Observed hinge axis has zero length'}
    direction/=length;delta=points-axis[0];along=delta@direction
    radial=delta-along[:,:,None]*direction;radius=np.linalg.norm(radial,axis=2)
    if (radius[0]<=precision_m).any():raise ValueError('Door radial witnesses must be separated from hinge axis')
    cross=np.cross(radial[0][None,:,:],radial)
    angle=np.arctan2(cross@direction,np.einsum('kj,nkj->nk',radial[0],radial))
    # Compare phases pairwise. No fitted rotation is applied to the surface.
    relative=angle-angle[:,:1]
    chord=2*radius[0][None,:]*np.abs(np.sin(relative/2))
    residual=np.maximum.reduce([np.abs(along-along[0]),np.abs(radius-radius[0]),chord])
    return error_row(residual.max(0),half_scale_m,precision_m,
        per_frame_witness_angles_radians=angle.tolist(),axis_world_m=axis.tolist(),
        per_frame_maximum_hinge_error_m=residual.max(1).tolist(),temporal_aggregation='maximum per fixed landmark')
