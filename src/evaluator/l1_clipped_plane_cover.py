"""Sufficient complete-face distance proof using clipped actual target faces.

A target triangle may cross a source-plane neighbourhood even when its far
vertices do not. Clip it to that neighbourhood before projection. Dilating
each projected convex piece by an inscribed disk preserves a 3D distance
upper bound; only their actual union may cover the complete source face.
"""
from __future__ import annotations

import time

import numpy as np
import shapely
from shapely.errors import GEOSException

from .l1_protected_surface import split_polygon
from .l1_revolution import EPSILON_M


def clipped_plane_cover(triangle, target, tolerance_m, *, deadline, cache=None):
    if (type(tolerance_m) not in (int, float) or not np.isfinite(tolerance_m)
            or tolerance_m <= 64*EPSILON_M or type(deadline) not in (int, float)
            or not np.isfinite(deadline)):
        raise ValueError('Invalid plane-cover tolerance or deadline')
    triangle = np.asarray(triangle, dtype=float)
    if triangle.shape != (3, 3) or not np.isfinite(triangle).all():
        raise ValueError('Expected finite source triangle')
    if time.monotonic() >= deadline:
        raise TimeoutError('Clipped-plane cover deadline exhausted')
    effective = tolerance_m-32*EPSILON_M
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    norm = float(np.linalg.norm(normal))
    if norm <= 1e-24:
        return None
    normal /= norm
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    normal = np.round(normal, 10)
    normal /= np.linalg.norm(normal)
    offset = round(float(triangle[0] @ normal), 12)
    plane_error = float(np.max(np.abs(triangle @ normal-offset)))
    if plane_error > EPSILON_M:
        return None
    cache = {} if cache is None else cache
    # Cache ownership includes the actual target object and tolerance; do not
    # let identical source planes reuse a different target's covering proof.
    owner = cache.get('target')
    if owner is not target or cache.get('tolerance_m') != tolerance_m:
        cache.clear()
        cache.update(target=target, tolerance_m=tolerance_m)
    key = (*normal, offset)
    try:
        if key not in cache:
            if len(cache) >= 258:
                return None
            axis = np.eye(3)[np.argmin(np.abs(normal))]
            u = np.cross(axis, normal)
            u /= np.linalg.norm(u)
            basis = np.column_stack((u, np.cross(normal, u)))
            origin = normal*offset
            heights = target.xyz @ normal-offset
            halfwidth = .8*effective
            selected = (heights.min(axis=1) <= halfwidth) & (heights.max(axis=1) >= -halfwidth)
            angles = np.arange(8)*np.pi/4
            disk = np.column_stack((np.cos(angles), np.sin(angles)))
            hulls, bound = [], 0.
            for index in np.flatnonzero(selected):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Target face clipping deadline exhausted')
                polygon, _ = split_polygon(target.xyz[index], normal, offset+halfwidth)
                if not len(polygon):
                    continue
                polygon, _ = split_polygon(polygon, -normal, -offset+halfwidth)
                if not len(polygon):
                    continue
                h = float(np.max(np.abs(polygon @ normal-offset)))
                if h >= effective:
                    continue
                radius = .99*np.sqrt(effective**2-h*h)
                projected = (polygon-origin) @ basis
                points = (projected[:, None]+radius*disk).reshape(-1, 2)
                hulls.append(shapely.convex_hull(shapely.MultiPoint(points)))
                bound = max(bound, float(np.hypot(h, radius))+EPSILON_M)
            if time.monotonic() >= deadline:
                raise TimeoutError('Clipped-plane union deadline exhausted')
            union = shapely.union_all(hulls)
            if not union.is_valid:
                return None
            shapely.prepare(union)
            cache[key] = origin, basis, union, bound
        origin, basis, union, bound = cache[key]
        projected_source = shapely.Polygon((triangle-origin) @ basis)
        covered = union.covers(projected_source) and union.covers(projected_source.boundary)
        if time.monotonic() >= deadline:
            raise TimeoutError('Clipped-plane result missed deadline')
        return bound if covered and bound < tolerance_m else None
    except (ValueError, GEOSException):
        return None
