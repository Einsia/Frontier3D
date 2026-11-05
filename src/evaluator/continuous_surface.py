"""Continuous surface kernels in fixed world metres, shared with Blender workers.

The caller supplies a nearest-triangle query. No vertex-nearest approximation,
registration, colour similarity, quality thresholds or legacy scores are used.
"""
import numpy as np


def triangle_areas(vertices, triangles):
    v, f = np.asarray(vertices, dtype=float), np.asarray(triangles)
    if (v.ndim != 2 or v.shape[1:] != (3,) or not np.isfinite(v).all() or
            f.ndim != 2 or f.shape[1:] != (3,) or f.dtype.kind not in 'iu' or
            (f < 0).any() or (f >= len(v)).any()):
        raise ValueError('Finite indexed triangle mesh required')
    xyz = v[f]
    return np.linalg.norm(np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0]), axis=1) / 2


def area_samples(vertices, triangles, count=32768, seed=20261016):
    areas = triangle_areas(vertices, triangles)
    if type(count) is not int or count <= 0 or type(seed) is not int or seed < 0:
        raise ValueError('Positive count and nonnegative seed required')
    total = float(areas.sum())
    if not np.isfinite(total) or total <= 0: raise ValueError('No nondegenerate surface area')
    values = np.random.default_rng(seed).random((count, 3))
    indices = np.searchsorted(np.cumsum(areas), values[:, 0] * total, side='right')
    selected = np.asarray(vertices, float)[np.asarray(triangles)[indices]]
    u, v = np.sqrt(values[:, 1]), values[:, 2]
    points = ((1-u)[:, None] * selected[:, 0] + (u*(1-v))[:, None] * selected[:, 1]
              + (u*v)[:, None] * selected[:, 2])
    return points, indices


def soft_values(distances, half_scale):
    values = np.asarray(distances, dtype=float)
    if not np.isfinite(values).all() or (values < 0).any(): raise ValueError('Finite nonnegative distances required')
    if not np.isfinite(half_scale) or half_scale <= 0: raise ValueError('Positive half scale required')
    return np.exp2(-values / half_scale)


def surface_raw(candidate_distances, reference_distances, half_scale, evidence, **metadata):
    a, b = (np.asarray(x, float) for x in (candidate_distances, reference_distances))
    if not len(a) or not len(b): raise ValueError('Both surface populations must be observed')
    soft_values(a, half_scale); soft_values(b, half_scale)
    return {'status': 'measured', 'candidate_normalized_distances': (a/half_scale).tolist(),
        'reference_normalized_distances': (b/half_scale).tolist(), 'half_scale_m': half_scale,
        'candidate_distances_m': a.tolist(), 'reference_distances_m': b.tolist(),
        'evidence': evidence, 'coordinate_space': 'world_metres', 'registration': 'none', **metadata}


def topology_defects(vertices, triangles, weld_m=1e-9):
    """Area touched by open/nonmanifold/inconsistently oriented mesh edges.

Smoothness and ordinary sharp edges are excluded. Coordinate welding uses the
frozen numeric precision only. Self-intersections need the separate solid check.
"""
    vertices, triangles = np.asarray(vertices, float), np.asarray(triangles)
    areas = triangle_areas(vertices, triangles)
    if weld_m <= 0 or not np.isfinite(weld_m): raise ValueError('Positive weld precision required')
    _, inverse = np.unique(np.round(vertices/weld_m).astype(np.int64), axis=0, return_inverse=True)
    faces = inverse[triangles]
    directed = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    keys, edge_ids, counts = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True)
    orientations = np.where(directed[:, 0] < directed[:, 1], 1, -1)
    sums = np.bincount(edge_ids, weights=orientations, minlength=len(keys))
    bad_edges = (counts != 2) | (sums != 0) | (keys[:, 0] == keys[:, 1])
    bad = bad_edges[edge_ids].reshape(3, -1).any(axis=0)
    bad |= areas <= 1e-18
    total = float(areas.sum())
    return {'surface_area_m2': total, 'defect_area_m2': float(areas[bad].sum()),
        'defect_fraction': float(areas[bad].sum()/total) if total > 0 else 1.,
        'boundary_edges': int((counts == 1).sum()), 'nonmanifold_edges': int((counts > 2).sum()),
        'inconsistent_edges': int(((counts == 2) & (sums != 0)).sum()),
        'degenerate_triangles': int((areas <= 1e-18).sum()),
        'weld_m': weld_m, 'self_intersections_measured': False}
