"""Pose-anchored surface correspondence for material attachment diagnostics.

The rotation comes from observed object poses, never a search over material
values. Actual hash-bound geometry must verify that proposal. Equivalent origin
changes are absorbed by surface centroids; deformation, unsupported internal
motion or missing pose evidence remains unavailable, not a material failure.
"""

from __future__ import annotations

import numpy as np

from .l1_rigid_shape import _rotation, surface_frame, triangle_bound
from .l1_surface import SurfaceMesh, compare_surfaces


def register_material_surface(left, right, a, b, *, tolerance_m, levels, convergence_m, seed):
    if any(record.get('volume_reliable') is not True for record in (left, right)):
        raise ValueError('Material motion requires validated closed solids')
    matrices = [np.asarray(record['matrix_world'], dtype=float) for record in (left, right)]
    for matrix in matrices:
        if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
                or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-12, rtol=0)
                or abs(np.linalg.det(matrix[:3, :3])) < 1e-15):
            raise ValueError('Invalid observed object pose')
    if np.sign(np.linalg.det(matrices[0][:3, :3])) != np.sign(np.linalg.det(matrices[1][:3, :3])):
        raise ValueError('Reflected state cannot establish proper-rigid material attachment')
    if (isinstance(tolerance_m, bool) or not np.isfinite(tolerance_m) or tolerance_m <= 0
            or len(levels) < 2 or any(type(n) is not int or not 1 <= n <= 65536 for n in levels)
            or list(levels) != sorted(set(levels)) or type(seed) is not int or seed < 0
            or isinstance(convergence_m, bool) or not np.isfinite(convergence_m) or convergence_m <= 0):
        raise ValueError('Invalid material registration precision policy')
    rotation = _rotation(matrices[1]) @ _rotation(matrices[0]).T
    ac, _ = surface_frame(a)
    bc, _ = surface_frame(b)
    moved = SurfaceMesh((b.vertices - bc) @ rotation + ac, b.triangles)
    bound = triangle_bound(a, moved)
    if bound is not None and bound <= tolerance_m:
        surface = {'method': 'triangle_bijection_rigid_bound', 'continuous_surface_bound': True,
                   'maximum_bound_m': bound}
    else:
        surface = compare_surfaces(a, moved, levels=levels, seed=seed, convergence_m=convergence_m)
        if not surface['converged'] or surface['levels'][-1]['sampled_max_m'] > tolerance_m:
            raise ValueError('Observed pose does not establish a rigid surface correspondence')
        surface['continuous_surface_bound'] = False
    evidence = {'protocol': 'l1-material-motion-v1', 'hard_gate': False,
                'method': 'observed_pose_rotation_surface_centroids_geometry_verified',
                'right_to_left_row_rotation': rotation.tolist(), 'left_center_m': ac.tolist(), 'right_center_m': bc.tolist(),
                'geometry_sha256': [left['mesh_payload']['sha256'], right['mesh_payload']['sha256']],
                'object_poses': [m.tolist() for m in matrices], 'surface': surface,
                'tolerance_m': tolerance_m, 'scale_fitted': False, 'reflection_allowed': False,
                'limitations': ['Pose-anchored attachment diagnostic, not universal animated-surface tracking',
                                'Internal symmetry/topology motion is not resolved by searching material values']}
    return moved, evidence
