"""Batched complete triangle distances, including interior edge/face crossings.

Floating-point feature distances, not a BVH approximation or sampled distance.
Degenerate triangles must already have been rejected by SurfaceMesh.
"""
import numpy as np

from .l1_surface import _distances_to_triangles


def _intersections(left, right):
    """Separating axes avoid dividing by nearly zero ray determinants.

    Face normals and all edge crosses cover noncoplanar triangles; in-plane
    edge normals also separate disjoint coplanar triangles. Zero axes impose
    no restriction. Common translation improves projection arithmetic.
    """
    anchor = left[0]
    left,right = left-anchor,right-anchor
    le,re = np.roll(left,-1,axis=0)-left,np.roll(right,-1,axis=1)-right
    ln,rn = np.cross(le[0],le[1]),np.cross(re[:,0],re[:,1])
    axes = np.concatenate((np.broadcast_to(ln,(len(right),1,3)),rn[:,None],
        np.cross(le[None,:,None,:],re[:,None,:,:]).reshape(-1,9,3),
        np.broadcast_to(np.cross(ln,le),(len(right),3,3)),np.cross(rn[:,None],re)),axis=1)
    a = np.einsum('nki,ji->nkj',axes,left)
    b = np.einsum('nki,nji->nkj',axes,right)
    separated = (a.min(axis=2)>b.max(axis=2)) | (b.min(axis=2)>a.max(axis=2))
    return ~separated.any(axis=1)


def triangle_distances(left, right):
    """One 3×3 triangle against N×3×3 triangles, with no fitted transform."""
    left,right = np.asarray(left,dtype=float),np.asarray(right,dtype=float)
    if left.shape != (3,3) or right.ndim != 3 or right.shape[1:] != (3,3) or not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError('Finite triangles required')
    if not len(right):
        return np.empty(0)
    repeated = np.broadcast_to(left,right.shape)
    best = np.full(len(right),np.inf)
    crossing = _intersections(left,right)
    for i in range(3):
        best = np.minimum(best,_distances_to_triangles(left[i],right))
        best = np.minimum(best,_distances_to_triangles(right[:,i],repeated))
    # Interior edge-edge minima. Endpoint minima are included in vertex/face
    # distances, including all parallel/coplanar endpoint-to-edge cases.
    p = np.repeat(left,3,axis=0)[None]
    q = np.tile(right,(1,3,1))
    u = np.repeat(np.roll(left,-1,axis=0)-left,3,axis=0)[None]
    v = np.tile(np.roll(right,-1,axis=1)-right,(1,3,1))
    normal = np.cross(u,v)
    denominator = np.sum(normal*normal,axis=2)
    nonparallel = denominator > 0
    divisor = np.where(nonparallel,denominator,1.)
    s = np.sum(np.cross(q-p,v)*normal,axis=2)/divisor
    t = np.sum(np.cross(q-p,u)*normal,axis=2)/divisor
    valid = nonparallel & (s>=0) & (s<=1) & (t>=0) & (t<=1)
    distances = np.linalg.norm(p+s[...,None]*u-q-t[...,None]*v,axis=2)
    best = np.minimum(best,np.min(np.where(valid,distances,np.inf),axis=1))
    best[crossing] = 0.
    return best
