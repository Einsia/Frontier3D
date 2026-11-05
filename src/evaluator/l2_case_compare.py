"""Evaluated-mesh roundoff tolerance conditional on identical native geometry."""
from __future__ import annotations

import hashlib
from pathlib import Path
import numpy as np

DERIVED=('evaluated_geometry_sha256','surface_order_independent_sha256','surface_triangles','support_points','bounds','dimensions','volume','geometry_evidence')


def full_mesh(obj,directory):
    evidence=obj.get('geometry_evidence',{})
    name=evidence.get('full_geometry_file')
    if not directory or not name:
        return None
    if Path(name).name!=name or Path(name).suffix!='.npz':
        raise ValueError('Unsafe full geometry evidence path')
    path=Path(directory)/name
    if path.is_symlink():raise ValueError('Linked full geometry evidence')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=evidence['full_geometry_sha256']:
            raise ValueError('Full geometry evidence hash changed')
    with np.load(path,allow_pickle=False) as data:
        vertices=data['vertices'];triangles=data['triangles']
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or not np.isfinite(vertices).all()
            or triangles.ndim!=2 or triangles.shape[1]!=3 or triangles.dtype.kind not in 'iu'
            or triangles.size and (triangles.min()<0 or triangles.max()>=len(vertices))):
        raise ValueError('Invalid full geometry arrays')
    return vertices,triangles


def align_evaluated_roundoff(scene, reference, tolerance=1e-5, *, directory=None, reference_directory=None):
    """Compare complete surfaces/sidecars and normalize a comparison copy only.

    Coordinates, hashes and sidecars in the original evidence remain untouched.
    Surface/support samples alone never establish dense-mesh equivalence.
    """
    result={**scene,'objects':dict(scene.get('objects',{}))};adjusted={}
    for name,before in reference.get('objects',{}).items():
        after=scene.get('objects',{}).get(name)
        if not after or before.get('type')!='MESH' or after.get('type')!='MESH':continue
        if not before.get('geometry_sha256') or before['geometry_sha256']!=after.get('geometry_sha256'):continue
        if all(before.get(k)==after.get(k) for k in DERIVED):continue
        dense=any(o.get('geometry_evidence',{}).get('status')=='sampled_surface' for o in (before,after))
        if dense:
            left=full_mesh(before,reference_directory);right=full_mesh(after,directory)
            if left is None or right is None:continue
            vertices,indices=left;other,other_indices=right
            if vertices.shape!=other.shape or not np.array_equal(indices,other_indices):continue
            maximum=float(np.max(np.abs(vertices-other))) if vertices.size else 0.
            triangles=vertices[indices]
        else:
            triangles=np.asarray(before.get('surface_triangles',[]),dtype=float)
            other=np.asarray(after.get('surface_triangles',[]),dtype=float)
            if not triangles.size or triangles.shape!=other.shape or not np.isfinite(triangles).all() or not np.isfinite(other).all():continue
            maximum=float(np.max(np.abs(triangles-other)))
        if maximum>tolerance:continue
        # Support-point selection is diagnostic; its cutoff may select different
        # vertices under roundoff. Equivalence is proved by the complete mesh.
        area=float(np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2)
        volume_delta=abs(before.get('volume',np.nan)-after.get('volume',np.nan))
        volume_bound=max(1e-10,3*tolerance*area)
        if not np.isfinite(volume_delta) or volume_delta>volume_bound:continue
        result['objects'][name]={**after,**{k:before[k] for k in DERIVED if k in before}}
        adjusted[name]={'max_coordinate_delta_m':maximum,'tolerance_m':tolerance,
            'volume_delta_m3':volume_delta,'volume_bound_m3':volume_bound,
            'native_geometry_sha256':before['geometry_sha256'],'full_triangles_compared':len(triangles),
            'full_binary_geometry':dense}
    return result,adjusted
