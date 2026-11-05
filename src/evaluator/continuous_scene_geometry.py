"""Measure inherited world geometry while preserving instance multiplicity."""
from collections import defaultdict,deque
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree
from .continuous_assembly_state import weights


def paired(first,second,*,half_scale_m,precision_m=1e-7,surface_fallback=None):
    v,f=np.asarray(first[0],float),np.asarray(first[1]);w,t=np.asarray(second[0],float),np.asarray(second[1])
    if not len(f) or not len(t):return {'score':0.,'reason':'Required nonempty surface absent'}
    if v.shape!=w.shape or not np.array_equal(f,t):
        if surface_fallback is None:raise ValueError('Changed vertex correspondence needs full-triangle surface comparison')
        return surface_fallback(first,second,half_scale_m)
    weight,_=weights(v,f);distance=np.linalg.norm(w-v,axis=1)
    errors=np.maximum(distance-precision_m,0)/half_scale_m
    return {'score':float(np.sum(weight*np.exp2(-errors))),'maximum_displacement_m':float(distance.max()),
        'mean_displacement_m':float(weight@distance),'vertices_compared':len(v),'half_scale_m':half_scale_m,
        'numeric_precision_m':precision_m,'method':'area-weighted corresponding world vertices; no registration'}


def complete_instances(before,after,loader,*,surface_fallback=None):
    a=defaultdict(list);b=defaultdict(list)
    for obj in before:
        if obj.get('geometry'):a[obj['object']].append(obj)
    for obj in after:
        if obj.get('geometry'):b[obj['object']].append(obj)
    if not a:raise ValueError('Protected geometry population is empty')
    rows=[]
    for name in sorted(a.keys()|b.keys()):
        original,current=a[name],b[name]
        buckets=defaultdict(deque)
        for j,obj in enumerate(current):buckets[obj['geometry']['sha256']].append(j)
        unmatched=[];exact=[];used=set()
        for i,obj in enumerate(original):
            queue=buckets[obj['geometry']['sha256']]
            if queue:
                j=queue.popleft();used.add(j);exact.append([i,j])
            else:unmatched.append(i)
        remaining=[j for j in range(len(current)) if j not in used]
        observations=[];score=1.
        if len(original)!=len(current):
            score=0.;observations.append({'score':0.,'reason':'Protected instance population added or removed',
                                          'expected':len(original),'actual':len(current)})
        if unmatched and remaining:
            ac=np.array([np.mean(original[i]['bounds_m'],axis=0) for i in unmatched])
            bc=np.array([np.mean(current[j]['bounds_m'],axis=0) for j in remaining])
            _,nearest=cKDTree(bc).query(ac)
            if len(unmatched)==len(remaining) and len(set(nearest.tolist()))==len(nearest):
                pairs=list(enumerate(nearest.tolist()))
            elif max(len(ac),len(bc))<=1024:
                ar,br=linear_sum_assignment(np.linalg.norm(ac[:,None,:]-bc[None,:,:],axis=2));pairs=list(zip(ar,br))
            else:raise ValueError('Large ambiguous inherited instance correspondence needs an explicit spatial partition')
            for ai,bj in pairs:
                left,right=original[unmatched[ai]],current[remaining[bj]]
                v,f=loader(left['geometry']);w,t=loader(right['geometry'])
                span=float(np.ptp(v[np.unique(f)],axis=0).max()) if len(f) else 0.
                if span<=0:raise ValueError('Protected baseline instance has zero geometric span')
                q=paired((v,f),(w,t),half_scale_m=.001*span,surface_fallback=surface_fallback)
                observations.append({'before_index':int(unmatched[ai]),'after_index':int(remaining[bj]),**q})
                score=min(score,q['score'])
        rows.append({'source_object':name,'score':score,'expected_instances':len(original),'actual_instances':len(current),
            'exact_payload_pairs':exact,'changed_pairs':observations})
    return {'score':min(row['score'] for row in rows),'source_groups':rows,
        'expected_instances':sum(map(len,a.values())),'actual_instances':sum(map(len,b.values())),
        'method':'full world-geometry multiset; identical payloads prove zero distance, other pairs measured continuously',
        'registration':'none','group_aggregation':'worst required inherited instance'}
