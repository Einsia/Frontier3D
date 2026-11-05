"""Target-focused, area-weighted scene-edit surface measurements in metres."""
import numpy as np
if __package__:
    from .continuous_surface import area_samples,surface_raw,triangle_areas
else:
    from continuous_surface import area_samples,surface_raw,triangle_areas


def triangle_keys(vertices,faces):
    """Exact world triangles, independent of vertex/face order and winding."""
    xyz=np.asarray(vertices,float)[np.asarray(faces)]
    if not np.isfinite(xyz).all():raise ValueError('Finite world geometry required')
    xyz[xyz==0]=0.  # Canonical signed zero; no tolerance or coordinate fitting.
    order=np.lexsort((xyz[:,:,2],xyz[:,:,1],xyz[:,:,0]),axis=1)
    xyz=np.take_along_axis(xyz,order[:,:,None],axis=1)
    return np.ascontiguousarray(xyz).reshape(-1,9).view(np.dtype((np.void,72))).reshape(-1)


def changed_triangles(candidate,baseline):
    """Subtract exact baseline triangle multiplicities, retaining all extras."""
    vertices,faces=candidate
    if not len(faces):return np.asarray(faces),{'candidate_triangles':0,'removed_exact_baseline_triangles':0}
    keys=triangle_keys(*candidate);base,counts=np.unique(triangle_keys(*baseline),return_counts=True)
    if not len(base):raise ValueError('Nonempty inherited baseline required')
    order=np.argsort(keys,kind='stable');ordered=keys[order]
    position=np.searchsorted(base,ordered);safe=np.minimum(position,len(base)-1)
    same=(position<len(base))&(base[safe]==ordered)
    starts=np.r_[True,ordered[1:]!=ordered[:-1]]
    rank=np.arange(len(keys))-np.maximum.accumulate(np.where(starts,np.arange(len(keys)),0))
    remove=same&(rank<counts[safe]);keep=np.ones(len(faces),bool);keep[order[remove]]=False
    return np.asarray(faces)[keep],{'candidate_triangles':len(faces),'removed_exact_baseline_triangles':int(remove.sum()),
                                  'remaining_triangles':int(keep.sum()),'registration':'none'}


def join(meshes):
    vertices=[];faces=[];offset=0
    for v,f in meshes:
        if not len(f):continue
        vertices.append(v);faces.append(f+offset);offset+=len(v)
    return (np.concatenate(vertices),np.concatenate(faces)) if vertices else (np.empty((0,3)),np.empty((0,3),int))


def compare(surfaces,parameters,query,evidence):
    baseline=surfaces['baseline'];candidate=surfaces['candidate'];required=surfaces['required']
    optional=surfaces.get('optional',(np.empty((0,3)),np.empty((0,3),int)))
    count=parameters['sample_count'];seed=parameters['random_seed'];epsilon=parameters['scope_epsilon_m']
    target_scale=parameters['target_half_scale_m'];keep_scale=parameters['preserve_half_scale_m']
    if not 0<epsilon<min(target_scale,keep_scale):raise ValueError('Scope precision must be smaller than scoring scales')
    if not len(baseline[1]) or not len(required[1]):raise ValueError('Frozen baseline and required target surfaces needed')
    absent=lambda reason:{'status':'absent','reason':reason,'evidence':evidence,'coordinate_space':'world_metres','registration':'none'}
    if not len(candidate[1]):return {k:absent('Candidate geometry absent') for k in ('target_surface','protected_native')}
    base_query=query(*baseline);candidate_query=query(*candidate)
    allowed=join([required,optional]);final=join([baseline,allowed]);final_query=query(*final)
    residual_faces,partition=changed_triangles(candidate,baseline)
    if len(residual_faces) and triangle_areas(candidate[0],residual_faces).sum()>0:
        residual=(candidate[0],residual_faces);allowed_query=query(*allowed);changed_query=query(*residual)
        target_points=area_samples(*required,count,seed)[0]
        target_mask=base_query.nearest(target_points)[0]>epsilon
        if not target_mask.any():raise ValueError('Required reference target has no observed new surface')
        changed_points=area_samples(*residual,count,seed+1)[0]
        changed_mask=base_query.nearest(changed_points)[0]>epsilon
        if changed_mask.any():
            precision=allowed_query.nearest(changed_points[changed_mask])[0]
            recall=changed_query.nearest(target_points[target_mask])[0]
            target=surface_raw(precision,recall,target_scale,evidence,
                required_target_samples=int(target_mask.sum()),changed_candidate_samples=int(changed_mask.sum()),
                required_target_draws=count,changed_candidate_draws=count,
                optional_geometry_policy='optional GT supports precision only; absent optional content never reduces recall')
        else:target=absent('No added surface observed in the frozen area-weighted sample; finite-sampling limitation')
    else:target=absent('Every candidate triangle is an unchanged inherited baseline triangle')
    base_points=area_samples(*baseline,count,seed+2)[0]
    candidate_points=area_samples(*candidate,count,seed+3)[0]
    _,nearest_final=final_query.nearest(candidate_points)
    kept=base_query.nearest(nearest_final)[0]<=epsilon
    if kept.any():
        preserve=surface_raw(base_query.nearest(candidate_points[kept])[0],candidate_query.nearest(base_points)[0],
            keep_scale,evidence,baseline_samples=count,candidate_protected_samples=int(kept.sum()))
    else:preserve=absent('No candidate surface projects to the inherited protected reference surface')
    for raw in (target,preserve):
        raw.update(sample_count=count,random_seed=seed,scope_epsilon_m=epsilon,exact_triangle_partition=partition,
            sampling='separate required target, added candidate, baseline and full candidate populations',
            minimum_query_triangle_area_m2=1e-18,scope='frozen reference target identities; candidate names and mesh splits unused')
    return {'target_surface':target,'protected_native':preserve}
