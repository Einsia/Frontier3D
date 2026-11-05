"""Bounded proper-rigid shape witnesses; never align assembly placement checks.

Object matrices and vertex ordering only propose transforms. Actual hash-bound
world surfaces decide whether a proposal is valid. Scale and reflection are
never fitted away. A failed bounded search is not a global non-congruence proof.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from .l1_surface import (
    SurfaceMesh,
    compare_surfaces,
    load_surface,
    sample_surface,
    surface_distances,
)

PROTOCOL = 'l1-rigid-shape-v1'


def surface_frame(mesh: SurfaceMesh) -> tuple[np.ndarray, np.ndarray]:
    """Exact triangle-area centroid/covariance, independent of tessellation."""
    anchor = mesh.vertices[0]
    triangles = mesh.xyz - anchor
    weights = mesh.areas / mesh.areas.sum()
    center = np.sum(triangles.mean(axis=1) * weights[:, None], axis=0)
    xyz = triangles - center
    summed = xyz.sum(axis=1)
    second = (np.einsum('nki,nkj->nij', xyz, xyz) + np.einsum('ni,nj->nij', summed, summed)) / 12
    covariance = np.sum(second * weights[:, None, None], axis=0)
    _, axes = np.linalg.eigh(covariance)
    return center + anchor, axes


def proper_fit(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(source.T @ target)
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    return u @ correction @ vt


def _rotation(matrix) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError('Invalid object transform')
    u, _, vt = np.linalg.svd(matrix[:3, :3])
    correction = np.eye(3)
    correction[-1, -1] = np.linalg.det(u @ vt)
    return u @ correction @ vt


def normal_frames(mesh: SurfaceMesh):
    normals = np.cross(mesh.xyz[:, 1] - mesh.xyz[:, 0], mesh.xyz[:, 2] - mesh.xyz[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    directions, indices = np.unique(np.round(normals, 10), axis=0, return_inverse=True)
    areas = np.bincount(indices, weights=mesh.areas)
    directions = directions[np.argsort(-areas, kind='stable')[:8]]
    for first, second in itertools.permutations(directions, 2):
        first = first / np.linalg.norm(first)
        second = second - first * np.dot(first, second)
        if np.linalg.norm(second) < 1e-8:
            continue
        second /= np.linalg.norm(second)
        for a, b in itertools.product((-1, 1), repeat=2):
            x, y = first * a, second * b
            yield np.column_stack((x, y, np.cross(x, y)))


def candidates(left: SurfaceMesh, right: SurfaceMesh, left_record: dict, right_record: dict):
    lc, la = surface_frame(left)
    rc, ra = surface_frame(right)
    proposals = [('translation_only', np.eye(3))]
    if len(left.vertices) == len(right.vertices):
        # A proposal, never an assertion that vertex indices identify surfaces.
        proposals.append(('vertex_order_proposal', proper_fit(right.vertices - rc, left.vertices - lc)))
    if 'matrix_world' in left_record and 'matrix_world' in right_record:
        try:
            proposals.append(('object_rotation_proposal', _rotation(right_record['matrix_world']) @ _rotation(left_record['matrix_world']).T))
        except (TypeError, ValueError, np.linalg.LinAlgError):
            pass  # A bad optional proposal cannot substitute for mesh evidence.
    for permutation in itertools.permutations(range(3)):
        for signs in itertools.product((-1, 1), repeat=3):
            local = np.eye(3)[:, permutation] @ np.diag(signs)
            rotation = ra @ local @ la.T
            if np.linalg.det(rotation) > 0:
                proposals.append(('surface_moment_axes', rotation))
    seen = set()
    for method, rotation in proposals:
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-10, rtol=0) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-10, rtol=0):
            continue
        key = tuple(np.round(rotation, 11).flat)
        if key not in seen:
            seen.add(key)
            yield method, rotation, lc, rc
    # Moment axes are ambiguous for cubes and other symmetric solids. Use
    # surface directions as additional hypotheses, including after remeshing.
    # This bounded fallback does not turn unresolved registration into failure.
    left_frame = next(normal_frames(left), None)
    if left_frame is not None:
        for right_frame in normal_frames(right):
            rotation = right_frame @ left_frame.T
            key = tuple(np.round(rotation, 11).flat)
            if key not in seen:
                seen.add(key)
                yield 'surface_normal_frame', rotation, lc, rc


def triangle_bound(left: SurfaceMesh, right: SurfaceMesh) -> float | None:
    """A triangle bijection bounds every barycentric point, not just samples."""
    if left.vertices.shape != right.vertices.shape or left.triangles.shape != right.triangles.shape:
        return None
    distances, mapping = cKDTree(left.vertices).query(right.vertices)
    if len(set(mapping.tolist())) != len(left.vertices):
        return None
    left_faces = sorted(map(tuple, np.sort(left.triangles, axis=1)))
    right_faces = sorted(map(tuple, np.sort(mapping[right.triangles], axis=1)))
    return float(distances.max()) if left_faces == right_faces else None


def compare_rigid_shape(left_record: dict, right_record: dict, *, trusted_root: Path,
                        tolerance_m: float, levels=(256, 1024, 4096), convergence_m=1e-5, seed=0) -> dict:
    report = {
        'protocol': PROTOCOL, 'status': 'not_measurable', 'hard_gate': False,
        'scope': 'shape_only_proper_rigid_witness_not_assembly_placement',
        'tolerance_m': tolerance_m, 'shape_match': None, 'inputs': {}, 'attempts': [],
        'limitations': ['Bounded registration is not a global non-congruence proof',
                        'Remeshed comparisons use finite surface samples, not a continuous Hausdorff bound',
                        'No material, role, clearance or explosion-legibility verdict'],
    }
    try:
        if isinstance(tolerance_m, bool) or not np.isfinite(tolerance_m) or tolerance_m <= 0:
            raise ValueError('Positive finite shape tolerance required')
        if (not levels or any(type(n) is not int or not 1 <= n <= 65536 for n in levels)
                or list(levels) != sorted(set(levels)) or len(levels) < 2
                or isinstance(convergence_m, bool) or not np.isfinite(convergence_m) or convergence_m <= 0
                or type(seed) is not int or seed < 0):
            raise ValueError('Invalid frozen surface sampling configuration')
        if any(record.get('volume_reliable') is not True for record in (left_record, right_record)):
            raise ValueError('Validated solids are required for shape-preservation evidence')
        for side, record in (('left', left_record), ('right', right_record)):
            report['inputs'][side] = {key: record['mesh_payload'][key] for key in ('path', 'sha256', 'coordinate_space')}
        left = load_surface(left_record['mesh_payload'], trusted_root)
        right = load_surface(right_record['mesh_payload'], trusted_root)
        best = None
        for method, rotation, lc, rc in candidates(left, right, left_record, right_record):
            aligned = SurfaceMesh((right.vertices - rc) @ rotation + lc, right.triangles)
            bound = triangle_bound(left, aligned)
            row = {'proposal': method, 'triangle_bound_m': bound}
            report['attempts'].append(row)
            measured = None
            if bound is not None and bound <= tolerance_m:
                measured = {'method': 'triangle_bijection_rigid_bound', 'maximum_bound_m': bound,
                            'continuous_surface_bound': True, 'converged': True}
            else:
                # Reject unsuitable proposals cheaply, but use bidirectional
                # full levels and all vertex/face sentinels for a witness.
                coarse = max(float(surface_distances(sample_surface(left, 32, seed), aligned).max()),
                             float(surface_distances(sample_surface(aligned, 32, seed + 1), left).max()))
                row['coarse_max_m'] = coarse
                best = coarse if best is None else min(best, coarse)
                if coarse > tolerance_m:
                    continue
                observed = compare_surfaces(left, aligned, levels=levels, seed=seed, convergence_m=convergence_m)
                row['sampled_max_m'] = observed['levels'][-1]['sampled_max_m']
                if observed['converged'] and observed['levels'][-1]['sampled_max_m'] <= tolerance_m:
                    measured = observed
                    measured.update(alignment='proper_rigid_shape_only', continuous_surface_bound=False)
            if measured is not None:
                report.update(status='ok', shape_match=True, witness={
                    'proposal': method, 'right_to_left_row_rotation': rotation.tolist(),
                    'right_center_m': rc.tolist(), 'left_center_m': lc.tolist(),
                    'determinant': float(np.linalg.det(rotation)), 'scale_fitted': False,
                    'reflection_allowed': False, 'surface': measured,
                })
                return report
        # Do not claim that search failure mathematically proves deformation.
        # Task-level gates require calibrated handling of registration ambiguity.
        report.update(reason='No proper-rigid witness within the bounded search and declared tolerance',
                      registration_status='unresolved', best_coarse_max_m=best)
    except (KeyError, TypeError, ValueError, OSError, np.linalg.LinAlgError) as error:
        report.update(status='not_measurable', reason=str(error))
    return report
