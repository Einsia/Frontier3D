"""Complete finite-face distance cover with an explicit normal/lateral budget."""
from __future__ import annotations

import numpy as np
import shapely
from shapely.errors import GEOSException

from .l1_revolution import EPSILON_M


def planar_tube_cover(triangle, target, tolerance, *, cache):
    """Return a certified upper distance or None, never infer from samples.

For each actual target triangle, h bounds all its distances to the source
plane. Its projected convex face plus an inscribed disk of radius
    .99*sqrt(t**2-h**2) stays inside the requested 3D neighbourhood. Different
target triangles may jointly cover a source face, but holes remain holes.
"""
    effective = tolerance-32*EPSILON_M
    if effective <= 0:
        return None
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    norm = np.linalg.norm(normal)
    if norm <= 1e-24:
        return None
    normal /= norm
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    normal = np.round(normal, 10)
    normal /= np.linalg.norm(normal)
    offset = round(float(triangle[0] @ normal), 12)
    if np.max(np.abs(triangle @ normal-offset)) > EPSILON_M:
        return None
    key = ('tube', *normal, offset, float(tolerance))
    try:
        if key not in cache:
            if len(cache) >= 1024:
                return None
            axis = np.eye(3)[np.argmin(np.abs(normal))]
            u = np.cross(axis, normal)
            u /= np.linalg.norm(u)
            basis = np.column_stack((u, np.cross(normal, u)))
            origin = normal*offset
            heights = np.max(np.abs(target.xyz @ normal-offset), axis=1)
            selected = heights < effective
            if not selected.any():
                cache[key] = None
            else:
                h = heights[selected]
                radius = np.sqrt(effective**2-h*h)*.99
                projected = (target.xyz[selected]-origin) @ basis
                angles = np.arange(8)*np.pi/4
                disk = np.column_stack((np.cos(angles), np.sin(angles)))
                vertices = (projected[:, :, None]+radius[:, None, None, None]*disk).reshape(-1, 24, 2)
                hulls = shapely.convex_hull(shapely.multipoints(vertices))
                union = shapely.union_all(hulls)
                if not union.is_valid:
                    return None
                shapely.prepare(union)
                bound = float(np.sqrt(h*h+radius*radius).max())+EPSILON_M
                cache[key] = origin, basis, union, bound
        entry = cache[key]
        if entry is None:
            return None
        origin, basis, union, bound = entry
        projected = shapely.Polygon((triangle-origin) @ basis)
        return bound if union.covers(projected) and union.covers(projected.boundary) else None
    except (ValueError, GEOSException):
        return None
