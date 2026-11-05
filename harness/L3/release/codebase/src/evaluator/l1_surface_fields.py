"""World-surface correspondence for independently authored UV/material fields.

No ICP, per-part registration, UV equality or triangle-index equality. Returned
barycentrics address each mesh's own triangle/loop UVs. Ties are explicit.
"""

from __future__ import annotations

import numpy as np


def triangle_projection(point, triangles):
    """Closest point and barycentrics on each nondegenerate triangle."""
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac, ap = b - a, c - a, point - a
    normal = np.cross(ab, ac)
    norm2 = np.einsum('ij,ij->i', normal, normal)
    plane = np.einsum('ij,ij->i', ap, normal)
    projected = point - normal * (plane / norm2)[:, None] - a
    u = np.einsum('ij,ij->i', np.cross(projected, ac), normal) / norm2
    v = np.einsum('ij,ij->i', np.cross(ab, projected), normal) / norm2
    bary = np.column_stack((1 - u - v, u, v))
    inside = (u >= 0) & (v >= 0) & (u + v <= 1)
    distance2 = np.where(inside, plane * plane / norm2, np.inf)
    for first, second in ((0, 1), (1, 2), (2, 0)):
        start, end = triangles[:, first], triangles[:, second]
        edge = end - start
        edge2 = np.einsum('ij,ij->i', edge, edge)
        t = np.clip(np.einsum('ij,ij->i', point - start, edge) / edge2, 0, 1)
        delta = point - start - t[:, None] * edge
        candidate = np.einsum('ij,ij->i', delta, delta)
        closer = candidate < distance2
        distance2 = np.where(closer, candidate, distance2)
        alternative = np.zeros_like(bary)
        alternative[:, first] = 1 - t
        alternative[:, second] = t
        bary[closer] = alternative[closer]
    return np.sqrt(np.maximum(distance2, 0)), bary


def sample_locations(mesh, count, seed):
    if type(count) is not int or count <= 0 or type(seed) is not int or seed < 0:
        raise ValueError('Positive sample count and nonnegative integer seed required')
    values = np.random.default_rng(seed).random((count, 3))
    cumulative = np.cumsum(mesh.areas)
    indices = np.minimum(np.searchsorted(cumulative, values[:, 0] * cumulative[-1], side='right'), len(mesh.xyz) - 1)
    u, v = np.sqrt(values[:, 1]), values[:, 2]
    bary = np.column_stack((1 - u, u * (1 - v), u * v))
    return {'points': np.einsum('ij,ijk->ik', bary, mesh.xyz[indices]), 'triangles': indices, 'barycentric': bary}


def surface_correspondence(points, target):
    """Exact broad phase; expose all numerically equidistant triangle hits.

    Consumers must resolve differing UV/material values at tied surfaces, not
    silently trust triangle ordering. Numerical ties use machine precision,
    never the task's (much larger) positional tolerance.
    """
    points = np.asarray(points, dtype=np.float64)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError('Correspondence requires finite 3D points')
    result = []
    _, first = target.tree.query(points)
    max_radius = float(target.radii.max())
    for point, index in zip(points, first, strict=True):
        upper = float(triangle_projection(point, target.xyz[[index]])[0][0])
        rounding = 32 * np.finfo(float).eps * max(1, float(np.linalg.norm(point)), upper, max_radius)
        indices = np.asarray(target.tree.query_ball_point(point, upper + max_radius + rounding), dtype=int)
        lower = np.linalg.norm(target.centers[indices] - point, axis=1) - target.radii[indices]
        selected = np.sort(indices[lower <= upper + rounding])
        if not len(selected):
            selected = np.array([index])
        distance, bary = triangle_projection(point, target.xyz[selected])
        minimum = float(distance.min())
        nearest = distance <= minimum + rounding
        result.append({'distance_m': minimum, 'triangles': selected[nearest],
                       'barycentric': bary[nearest], 'tie_epsilon_m': rounding})
    return result


def interpolate_uv(layers, triangles, barycentric):
    indices = np.asarray(triangles)
    bary = np.asarray(barycentric, dtype=np.float64)
    if (indices.dtype.kind not in 'iu' or indices.ndim != 1 or bary.shape != (len(indices), 3)
            or not np.isfinite(bary).all() or (bary < -1e-12).any()
            or not np.allclose(bary.sum(axis=1), 1, atol=1e-12, rtol=0)):
        raise ValueError('Invalid surface field addresses')
    result = {}
    for name, coordinates in layers.items():
        values = np.asarray(coordinates)
        if (values.ndim != 3 or values.shape[1:] != (3, 2) or not np.isfinite(values).all()
                or (indices < 0).any() or (indices >= len(values)).any()):
            raise ValueError('Invalid triangle-bound UV layer')
        result[name] = np.einsum('ij,ijk->ik', bary, values[indices])
    return result
