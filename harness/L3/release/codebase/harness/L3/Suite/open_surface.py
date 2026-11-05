"""Proper non-coplanar crossings for render meshes that do not enclose a solid.

No hole filling, convex hull or invented volume. Closed meshes retain the exact
volume/SAT path; this path measures only actual triangle surface crossings.
"""
import numpy as np

def _slice(triangle, distances, axis):
    points=[]
    for i in range(3):
        j=(i+1)%3;a,b=distances[i],distances[j]
        if abs(a)<1e-9:points.append(triangle[i])
        if a*b<0:points.append(triangle[i]+(triangle[j]-triangle[i])*a/(a-b))
    if len(points)<2:return None
    values=np.asarray(points)@axis
    return float(values.min()),float(values.max())

def crossing(left,right,tolerance):
    if len(left)>len(right):left,right=right,left
    low=right.min(1);high=right.max(1)
    # A triangle outside the other mesh's aggregate AABB cannot pass any
    # per-triangle AABB test below. Preserve original order and exact tests.
    if len(left):
        left_low=left.min(axis=(0,1));left_high=left.max(axis=(0,1))
        relevant=np.all(high>=left_low,axis=1)&np.all(low<=left_high,axis=1)
        right=right[relevant];low=low[relevant];high=high[relevant]
    normals=np.cross(right[:,1]-right[:,0],right[:,2]-right[:,0])
    lengths=np.linalg.norm(normals,axis=1);valid=lengths>1e-10
    normals=normals/np.maximum(lengths[:,None],1e-10)
    tested=0
    for tri in left:
        n=np.cross(tri[1]-tri[0],tri[2]-tri[0]);length=np.linalg.norm(n)
        if length<1e-10:continue
        n=n/length
        ids=np.flatnonzero(valid & np.all(high>=tri.min(0),axis=1) & np.all(low<=tri.max(0),axis=1))
        if not len(ids):continue
        da=(right[ids]-tri[0])@n
        # Both surfaces must cross the other's plane, beyond numerical/contact tolerance.
        mask=(da.min(1)<-tolerance-1e-8)&(da.max(1)>tolerance+1e-8)
        ids=ids[mask];da=da[mask]
        if not len(ids):continue
        db=np.einsum('nij,nj->ni',tri[None,:,:]-right[ids,0,None,:],normals[ids])
        mask=(db.min(1)<-tolerance-1e-8)&(db.max(1)>tolerance+1e-8)
        for idx,d_a,d_b in zip(ids[mask],da[mask],db[mask]):
            tested+=1;axis=np.cross(n,normals[idx]);norm=np.linalg.norm(axis)
            if norm<1e-9:continue
            axis=axis/norm
            a=_slice(tri,d_b,axis);b=_slice(right[idx],d_a,axis)
            if a and b and min(a[1],b[1])-max(a[0],b[0])>tolerance+1e-8:
                return {'method':'open_surface_proper_triangle_crossing','violates':True,'tested_crossing_pairs':tested,'tolerance_cm':tolerance}
    return {'method':'open_surface_proper_triangle_crossing','violates':False,'tested_crossing_pairs':tested,'tolerance_cm':tolerance,
            'scope':'Proper noncoplanar surface crossings only; open surfaces do not define containment volume.'}
