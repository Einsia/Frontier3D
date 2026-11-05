"""Guarded triangle-patch separation bounds against every target triangle."""
from __future__ import annotations

import numpy as np

from .l1_revolution import EPSILON_M, point_triangle_distances


def _edge_hits_face(starts, ends, faces):
    """Broadcast segment/triangle intersections; parallel cases stay cautious."""
    a, b, c = faces[..., 0, :], faces[..., 1, :], faces[..., 2, :]
    ab, ac = b-a, c-a
    normal = np.cross(ab, ac)
    norm2 = np.sum(normal*normal, axis=-1)
    direction = ends-starts
    denominator = np.sum(direction*normal, axis=-1)
    numerator = np.sum((a-starts)*normal, axis=-1)
    scale = np.sqrt(norm2)*np.linalg.norm(direction, axis=-1)
    stable = np.abs(denominator) > 128*np.finfo(float).eps*scale
    parameter = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=stable)
    point = starts+parameter[..., None]*direction
    projected = point-a
    u = np.sum(np.cross(projected, ac)*normal, axis=-1)/norm2
    v = np.sum(np.cross(ab, projected)*normal, axis=-1)/norm2
    guard = 1e-10
    hits = stable & (parameter >= -guard) & (parameter <= 1+guard) & (u >= -guard) & (v >= -guard) & (u+v <= 1+guard)
    # Clip a nearly coplanar segment's barycentrics against the actual face;
    # lying on an infinite plane does NOT mean touching its bounded triangle.
    end_projected = ends-a
    ue = np.sum(np.cross(end_projected, ac)*normal, axis=-1)/norm2
    ve = np.sum(np.cross(ab, end_projected)*normal, axis=-1)/norm2
    left, right = np.zeros_like(u), np.ones_like(u)
    possible = np.ones_like(u, dtype=bool)
    for first, last in ((u, ue), (v, ve), (1-u-v, 1-ue-ve)):
        change = last-first
        crossing = np.divide(-guard-first, change, out=np.zeros_like(first), where=change != 0)
        left = np.maximum(left, np.where(change > 0, crossing, -np.inf))
        right = np.minimum(right, np.where(change < 0, crossing, np.inf))
        possible &= (change != 0) | (first >= -guard)
    near_parallel = (~stable & (np.abs(numerator) <= EPSILON_M*np.sqrt(norm2))
                     & possible & (left <= right))
    return hits | near_parallel


def triangle_pair_distances(triangle, targets):
    """Minimum over vertex/face, edge/edge and edge/face intersection cases."""
    triangle, targets = np.asarray(triangle), np.asarray(targets)
    if np.linalg.norm(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])) <= 1e-24:
        return np.zeros(len(targets))
    distance = np.min(np.stack([point_triangle_distances(vertex, targets) for vertex in triangle]), axis=0)
    for index in range(3):
        distance = np.minimum(distance, point_triangle_distances(targets[:, index], triangle))
    edges_a = np.roll(triangle, -1, axis=0)-triangle
    starts_b = targets
    edges_b = np.roll(targets, -1, axis=1)-targets
    # End-point minima are already contained in vertex/face distances. The
    # remaining edge/edge minimum is their interior stationary point.
    for index, edge in enumerate(edges_a):
        offset = triangle[index]-starts_b
        aa = float(edge @ edge)
        bb = np.sum(edges_b*edges_b, axis=-1)
        ab = np.sum(edge*edges_b, axis=-1)
        aw = np.sum(edge*offset, axis=-1)
        bw = np.sum(edges_b*offset, axis=-1)
        determinant = aa*bb-ab*ab
        stable = determinant > 128*np.finfo(float).eps*aa*bb
        s = np.divide(ab*bw-bb*aw, determinant, out=np.zeros_like(determinant), where=stable)
        t = np.divide(aa*bw-ab*aw, determinant, out=np.zeros_like(determinant), where=stable)
        valid = stable & (s >= 0) & (s <= 1) & (t >= 0) & (t <= 1)
        separation = np.linalg.norm(offset+s[..., None]*edge-t[..., None]*edges_b, axis=-1)
        distance = np.minimum(distance, np.where(valid, separation, np.inf).min(axis=1))
        # Near-parallel stationary parameters can be ill-conditioned. Relax
        # the target segment to its infinite line and minimize over the whole
        # source segment, yielding a conservative lower bound instead.
        perpendicular = offset-(bw/bb)[..., None]*edges_b
        perpendicular_edge = edge-(ab/bb)[..., None]*edges_b
        denominator = np.sum(perpendicular_edge*perpendicular_edge, axis=-1)
        parameter = np.clip(np.divide(-np.sum(perpendicular*perpendicular_edge, axis=-1), denominator,
            out=np.zeros_like(denominator), where=denominator > 0), 0, 1)
        line_lower = np.linalg.norm(perpendicular+parameter[..., None]*perpendicular_edge, axis=-1)
        amin, amax = np.minimum(triangle[index], triangle[index]+edge), np.maximum(triangle[index], triangle[index]+edge)
        bmin, bmax = np.minimum(starts_b, starts_b+edges_b), np.maximum(starts_b, starts_b+edges_b)
        box_lower = np.linalg.norm(np.maximum(np.maximum(bmin-amax, amin-bmax), 0.), axis=-1)
        parallel_lower = np.maximum(line_lower, box_lower)
        distance = np.minimum(distance, np.where(~stable, parallel_lower, np.inf).min(axis=1))
        hit = _edge_hits_face(triangle[index], triangle[(index+1) % 3], targets)
        distance = np.where(hit, 0., distance)
    for index in range(3):
        hit = _edge_hits_face(targets[:, index], targets[:, (index+1) % 3], triangle)
        distance = np.where(hit, 0., distance)
    scale = max(float(np.abs(triangle).max()), float(np.abs(targets).max()), 1.)
    return np.maximum(0., distance-(EPSILON_M+128*np.finfo(float).eps*scale))


def clearance_lower(triangle, target, threshold, *, boxes=None):
    """A lower bound to ALL target faces, not just nearest-centroid choices.

    AABB separation is used only as a lower bound. Near boxes use actual
    triangle-pair separation including intersections; no bounding-box overlap
    is interpreted as an actual intersection or geometry match.
    """
    low, high = boxes if boxes is not None else (target.xyz.min(axis=1), target.xyz.max(axis=1))
    gaps = np.maximum(np.maximum(low-triangle.max(axis=0), triangle.min(axis=0)-high), 0.)
    lower = np.maximum(0., np.linalg.norm(gaps, axis=1)-EPSILON_M)
    near = lower <= threshold+EPSILON_M
    if near.any():
        lower[near] = np.maximum(lower[near], triangle_pair_distances(triangle, target.xyz[near]))
    return float(lower.min())
