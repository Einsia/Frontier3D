"""Guarded sections of a target triangle's normal prism in source z=0.

Distance to the target's infinite plane is a necessary tube constraint, not a
sufficient one. The interior of its three edge halfspaces additionally proves
that the orthogonal foot is on the actual triangle. Edge/vertex round tubes
remain the responsibility of the caller; this prism never fills missing faces.
"""
from __future__ import annotations

import numpy as np
import shapely

from .l1_revolution import EPSILON_M

GUARD = 4*EPSILON_M
CIRCLE_SIDES = 128
ANGLES = np.arange(CIRCLE_SIDES)*2*np.pi/CIRCLE_SIDES
CIRCLE = np.column_stack((np.cos(ANGLES), np.sin(ANGLES)))


def clip_convex(points, normal, offset):
    """Clip a convex 2D polygon by dot(point, normal) <= offset."""
    if len(points) < 3:
        return np.empty((0, 2))
    values = points @ normal-offset
    inside = values <= 0
    if inside.all():
        return points
    if not inside.any():
        return np.empty((0, 2))
    following = np.roll(points, -1, axis=0)
    next_values = np.roll(values, -1)
    crossing = inside != np.roll(inside, -1)
    # Crossings have opposite-sided values, so this divisor is nonzero.
    intersections = points[crossing]+(values[crossing]/(values[crossing]-next_values[crossing]))[:, None]*(
        following[crossing]-points[crossing])
    expanded = np.empty((len(points), 2, 2))
    expanded[:, 0] = points
    expanded[crossing, 1] = intersections
    return expanded.reshape(-1, 2)[np.column_stack((inside, crossing)).reshape(-1)]


def _polygon(points):
    return shapely.Polygon(points) if len(points) >= 3 else shapely.GeometryCollection()


def triangle_prism_section(face, outer, tolerance):
    """Tighten a known outer tube and construct a certified inner prism.

    Inputs are in the source frame; source points have local z=0. The source
    frame may differ from an original descendant plane by <=1 nm, which is
    covered by the unchanged 4 nm metric guards on every linear constraint.
    """
    normal = np.cross(face[1]-face[0], face[2]-face[0])
    norm = np.linalg.norm(normal)
    if not np.isfinite(norm) or norm <= 1e-24 or outer.is_empty:
        return outer, shapely.GeometryCollection()
    normal /= norm
    offset = float(face[0] @ normal)
    points = np.asarray(outer.exterior.coords)[:-1]
    for vector, limit in ((normal[:2], offset+tolerance+GUARD),
                          (-normal[:2], -offset+tolerance+GUARD)):
        points = clip_convex(points, vector, limit)
    tightened = _polygon(points)
    inner = points
    for vector, limit in ((normal[:2], offset+tolerance-GUARD),
                          (-normal[:2], -offset+tolerance-GUARD)):
        inner = clip_convex(inner, vector, limit)
    # m is in the target plane, so m·(p - h*n - a) == m·(p - a).
    # These constraints apply to the actual orthogonal foot, not the source
    # plane projection of the target vertices (which differs for tilted faces).
    for start, end in zip(face, np.roll(face, -1, axis=0), strict=True):
        edge = end-start
        size = np.linalg.norm(edge)
        if not np.isfinite(size) or size <= 1e-24:
            return tightened, shapely.GeometryCollection()
        inward = np.cross(normal, edge)/size
        inner = clip_convex(inner, -inward[:2], -float(inward @ start)-GUARD)
    return tightened, _polygon(inner)


def edge_inner_sections(face, tolerance):
    """Inscribed sections of the three finite edge cylinders and vertex balls.

    The triangle distance tube is its normal prism plus these round edge and
    vertex pieces. No target-height sampling is needed. Ill-conditioned edge
    ellipses may be omitted from this INNER set; that only retains uncertainty.
    """
    radius = tolerance-GUARD
    pieces = []
    for point in face:
        if abs(point[2]) < radius:
            reach = np.sqrt(radius*radius-point[2]*point[2])
            pieces.append(shapely.Polygon(point[:2]+reach*CIRCLE))
    for start, end in zip(face, np.roll(face, -1, axis=0), strict=True):
        if min(start[2], end[2]) >= radius or max(start[2], end[2]) <= -radius:
            continue
        edge = end-start
        length = np.linalg.norm(edge)
        if not np.isfinite(length) or length <= 2*GUARD:
            continue
        direction = edge/length
        if direction[2] == 0:
            reach = np.sqrt(max(0., radius*radius-start[2]*start[2]))
            perpendicular = np.array([-direction[1], direction[0]])
            left = start[:2]+GUARD*direction[:2]
            right = end[:2]-GUARD*direction[:2]
            points = np.array([left-reach*perpendicular, right-reach*perpendicular,
                               right+reach*perpendicular, left+reach*perpendicular])
        elif abs(direction[2]) >= 1e-8:
            center = start[:2]-start[2]*direction[:2]/direction[2]
            horizontal = np.linalg.norm(direction[:2])
            along = direction[:2]/horizontal if horizontal else np.array([1., 0.])
            across = np.array([-along[1], along[0]])
            points = center+radius*(CIRCLE[:, 0, None]*along/abs(direction[2])+CIRCLE[:, 1, None]*across)
            offset = float(direction @ start)
            points = clip_convex(points, -direction[:2], -offset-GUARD)
            points = clip_convex(points, direction[:2], offset+length-GUARD)
        else:
            continue
        polygon = _polygon(points)
        if not polygon.is_empty and polygon.is_valid:
            pieces.append(polygon)
    return pieces
