"""Bounded, two-sided comparison to an analytic surface of revolution.

The reference is a closed polyline in (radius, Z), revolved about a fixed Z
axis. No object names, vertex correspondence, ICP or scale fitting are used.
Passing requires upper bounds, not only small errors at sampled points.
An exhausted subdivision budget is unavailable evidence, never a pass.
"""
from __future__ import annotations

import numpy as np

from .l1_surface import SurfaceMesh, surface_distances

PROTOCOL = 'l1-revolution-bounds-v1'
EPSILON_M = 1e-9


def profile_array(profile):
    points = np.asarray(profile, dtype=float)
    if (points.ndim != 2 or points.shape[1:] != (2,) or not 3 <= len(points) <= 64
            or not np.isfinite(points).all() or (points[:, 0] <= 0).any()
            or (np.linalg.norm(np.roll(points, -1, axis=0)-points, axis=1) <= EPSILON_M).any()):
        raise ValueError('Expected 3–64 finite positive-radius nonduplicate profile vertices')
    return points


def revolve(profile, segments, *, angles=None):
    """An inscribed polygonal reference with an explicit analytic sagitta bound."""
    profile = profile_array(profile)
    if type(segments) is not int or not 16 <= segments <= 4096:
        raise ValueError('Invalid angular resolution')
    angles = np.arange(segments) * (2*np.pi/segments) if angles is None else np.asarray(angles)
    if angles.shape != (segments,) or not np.isfinite(angles).all() or np.any(np.diff(angles) <= 0):
        raise ValueError('Angular grid must be finite and strictly increasing')
    gaps = np.diff(np.r_[angles, angles[0]+2*np.pi])
    if gaps.min() <= 0 or gaps.max() >= np.pi:
        raise ValueError('Angular grid must cover a full circle with small gaps')
    vertices = np.stack((profile[:, 0, None]*np.cos(angles),
                         profile[:, 0, None]*np.sin(angles),
                         np.broadcast_to(profile[:, 1, None], (len(profile), segments))), axis=2).reshape(-1, 3)
    triangles = []
    for j in range(len(profile)):
        k = (j+1) % len(profile)
        for i in range(segments):
            nxt = (i+1) % segments
            a, b, c, d = j*segments+i, j*segments+nxt, k*segments+nxt, k*segments+i
            triangles.extend(((a, b, c), (a, c, d)))
    return SurfaceMesh(vertices, np.asarray(triangles)), float(profile[:, 0].max()*(1-np.cos(gaps.max()/2)))


def segment_distances(points, profile):
    """Distances from arbitrary (..., 2) meridian points to every profile edge."""
    starts = profile
    edges = np.roll(profile, -1, axis=0)-starts
    delta = np.asarray(points)[..., None, :]-starts
    t = np.clip((delta*edges).sum(axis=-1)/(edges*edges).sum(axis=-1), 0, 1)
    return np.linalg.norm(delta-t[..., None]*edges, axis=-1)


def triangle_to_analytic_bounds(triangles, profile):
    radii = np.linalg.norm(triangles[..., :2], axis=-1)
    meridian = np.stack((radii, triangles[..., 2]), axis=-1)
    distances = segment_distances(meridian, profile)
    centers = triangles.mean(axis=1)
    center_meridian = np.stack((np.linalg.norm(centers[:, :2], axis=-1), centers[:, 2]), axis=-1)
    lower = np.maximum(distances.min(axis=-1).max(axis=-1), segment_distances(center_meridian, profile).min(axis=-1))
    angles = np.sort(np.arctan2(triangles[..., 1], triangles[..., 0]), axis=-1)
    gaps = np.concatenate((np.diff(angles, axis=-1), (angles[:, :1]+2*np.pi-angles[:, -1:])), axis=-1)
    spread = 2*np.pi-gaps.max(axis=-1)
    # Radial norm is convex. Its departure from the affine interpolation of
    # vertex radii is bounded by the angular cone's sagitta (or max radius if
    # that cone contains a half-circle). Z is affine. Distance to a convex
    # segment is convex, hence max(vertex distances)+this departure bounds
    # every point of the triangle, not just its vertices.
    deficit = radii.max(axis=-1)*np.where(spread <= np.pi, 1-np.cos(spread/2), 1.)
    upper = distances.max(axis=1).min(axis=-1)+deficit
    return lower, upper


def point_triangle_distances(points, triangles):
    """Broadcast Euclidean point-to-triangle distances, including edge regions."""
    a, b, c = triangles[..., 0, :], triangles[..., 1, :], triangles[..., 2, :]
    ab, ac, ap = b-a, c-a, points-a
    normal = np.cross(ab, ac)
    norm2 = (normal*normal).sum(axis=-1)
    dot = (ap*normal).sum(axis=-1)
    projection = ap-normal*(dot/norm2)[..., None]
    u = (np.cross(projection, ac)*normal).sum(axis=-1)/norm2
    v = (np.cross(ab, projection)*normal).sum(axis=-1)/norm2
    distance2 = np.where((u >= 0) & (v >= 0) & (u+v <= 1), dot*dot/norm2, np.inf)
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end-start
        t = np.clip(((points-start)*edge).sum(axis=-1)/(edge*edge).sum(axis=-1), 0, 1)
        delta = points-start-t[..., None]*edge
        distance2 = np.minimum(distance2, (delta*delta).sum(axis=-1))
    return np.sqrt(np.maximum(distance2, 0))


def convex_patch_neighbors(target):
    """Certified convex two-triangle patches, never a hull over missing faces.

    Long quad faces may be triangulated with either diagonal. Bounding distance
    to each triangle alone makes that harmless choice prohibitively expensive.
    Only edge-adjacent pairs with a convex planar projection are joined. The
    actual mesh is unchanged; twice the planarity error covers projection and
    lifting. Nonplanar patches have larger bounds, not an assumed flat surface;
    concave projected and nonmanifold pairs are not joined.
    """
    neighbors = np.repeat(np.arange(len(target.xyz))[:, None], 3, axis=1)
    error = np.zeros(neighbors.shape)
    edges = {}
    for index, triangle in enumerate(target.triangles):
        for slot in range(3):
            edge = tuple(sorted((int(triangle[slot]), int(triangle[(slot+1) % 3]))))
            edges.setdefault(edge, []).append((index, slot, int(triangle[(slot+2) % 3])))
    for (a, b), uses in edges.items():
        if len(uses) != 2:
            continue
        (i, si, u), (j, sj, v) = uses
        polygon = target.vertices[[u, a, v, b]].copy()
        normal = np.cross(polygon[1]-polygon[0], polygon[3]-polygon[0])
        normal /= np.linalg.norm(normal)
        heights = (polygon-polygon[0]) @ normal
        deviation = float(np.abs(heights).max())
        polygon -= heights[:, None]*normal
        sides = np.roll(polygon, -1, axis=0)-polygon
        turns = np.cross(sides, np.roll(sides, -1, axis=0)) @ normal
        if not (np.all(turns > 1e-20) or np.all(turns < -1e-20)):
            continue
        neighbors[i, si], neighbors[j, sj] = j, i
        error[i, si] = error[j, sj] = 2*deviation
    return neighbors, error


def triangle_to_mesh_upper(triangles, target, patches=None):
    _, centers = target.tree.query(triangles.mean(axis=1), k=min(4, len(target.xyz)))
    if centers.ndim == 1:
        centers = centers[:, None]
    _, vertices = target.tree.query(triangles.reshape(-1, 3))
    indices = np.concatenate((centers, vertices.reshape(-1, 3)), axis=1)
    choices = target.xyz[indices]
    distances = np.stack([point_triangle_distances(triangles[:, i, None, :], choices) for i in range(3)])
    # Each target triangle is convex; the maximum of its three vertex
    # distances bounds the entire source triangle. Choosing only nearby
    # targets affects speed/tightness, never the validity of the upper bound.
    upper = distances.max(axis=0).min(axis=1)
    if patches is not None:
        neighbors, guard = patches
        others = target.xyz[neighbors[indices]]
        paired = np.stack([point_triangle_distances(triangles[:, i, None, None, :], others) for i in range(3)])
        paired = np.minimum(distances[..., None], paired)
        upper = np.minimum(upper, (paired.max(axis=0)+guard[indices]).min(axis=(1, 2)))
    return upper


def subdivide(triangles):
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, bc, ca = (a+b)/2, (b+c)/2, (c+a)/2
    return np.concatenate([np.stack(points, axis=1) for points in
                           ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])


def directed_bound(triangles, *, tolerance_m, profile=None, target=None,
                   approximation_m=0., max_patches=262144, max_depth=12):
    pending = triangles
    processed = 0
    proved_upper = approximation_m
    witness_lower = 0.
    patches = convex_patch_neighbors(target) if target is not None else None
    for depth in range(max_depth+1):
        remaining = []
        for start in range(0, len(pending), 512):
            batch = pending[start:start+512]
            if processed+len(batch) > max_patches:
                return {'status': 'not_measurable', 'reason': 'Subdivision patch budget exhausted',
                        'processed_patches': processed, 'witness_lower_bound_m': witness_lower,
                        'continuous_upper_bound_m': None}
            processed += len(batch)
            if profile is not None:
                lower, upper = triangle_to_analytic_bounds(batch, profile)
                witness_lower = max(witness_lower, float(lower.max()))
            else:
                upper = triangle_to_mesh_upper(batch, target, patches)+approximation_m
                # Exact nearest-surface queries supply rejection witnesses;
                # approximate nearest-centroid candidates are never used to
                # reject geometry. A few witnesses suffice to reject, but all
                # patches must be bounded before a pass.
                if np.max(upper) > tolerance_m:
                    selected = np.argsort(upper)[-4:]
                    points = batch[selected].reshape(-1, 3)
                    lower = np.maximum(surface_distances(points, target)-approximation_m, 0.)
                    witness_lower = max(witness_lower, float(lower.max()))
            if witness_lower > tolerance_m+EPSILON_M:
                return {'status': 'failed', 'reason': 'Actual surface-distance witness exceeds tolerance',
                        'processed_patches': processed, 'witness_lower_bound_m': witness_lower,
                        'continuous_upper_bound_m': None}
            accepted = upper < tolerance_m-EPSILON_M
            if accepted.any():
                proved_upper = max(proved_upper, float(upper[accepted].max()))
            if (~accepted).any():
                remaining.append(batch[~accepted])
        if not remaining:
            return {'status': 'passed', 'processed_patches': processed, 'depth': depth,
                    'witness_lower_bound_m': witness_lower, 'continuous_upper_bound_m': proved_upper}
        unresolved = np.concatenate(remaining)
        if processed+4*len(unresolved) > max_patches:
            break
        pending = subdivide(unresolved)
    return {'status': 'not_measurable', 'reason': 'Unresolved patches at subdivision/depth limit',
            'processed_patches': processed, 'witness_lower_bound_m': witness_lower,
            'continuous_upper_bound_m': None}


def compare_revolution(mesh, profile, tolerance_m, *, center_xy=(0., 0.), max_patches=262144):
    profile = profile_array(profile)
    center = np.asarray([*center_xy, 0.], dtype=float)
    if (center.shape != (3,) or not np.isfinite(center).all() or not np.isfinite(tolerance_m)
            or tolerance_m <= 4*EPSILON_M or type(max_patches) is not int or max_patches <= 0):
        raise ValueError('Invalid revolution comparison budget, datum or tolerance')
    local = SurfaceMesh(mesh.vertices-center, mesh.triangles)
    count = 32
    while count < 4096 and profile[:, 0].max()*(1-np.cos(np.pi/count)) > tolerance_m/16:
        count *= 2
    # Refine the analytic surface's integration grid at candidate azimuths.
    # This changes neither the analytic geometry nor its datum/tolerance. The
    # maximum angular gap still gives a bound over the ENTIRE reference. It
    # avoids needless subdivisions where two equivalent polygonal meshes put
    # their angular seams differently. Fall back to the uniform bounded grid
    # for arbitrary dense meshes rather than exceeding a resource limit.
    angles = np.sort(np.mod(np.arctan2(local.vertices[:, 1], local.vertices[:, 0]), 2*np.pi))
    angles = angles[np.r_[True, np.diff(angles) > 1e-5]]
    if len(angles)+count <= 4096:
        angles = np.unique(np.r_[np.arange(count)*(2*np.pi/count), angles])
        angles = angles[np.r_[True, np.diff(angles) > 1e-5]]
        if 2*np.pi+angles[0]-angles[-1] < 1e-5:
            angles = angles[:-1]
    else:
        angles = np.arange(count)*(2*np.pi/count)
    reference, sagitta = revolve(profile, len(angles), angles=angles)
    if sagitta >= tolerance_m:
        raise ValueError('Reference approximation is coarser than physical tolerance')
    forward = directed_bound(local.xyz, tolerance_m=tolerance_m, profile=profile, max_patches=max_patches)
    reverse = directed_bound(reference.xyz, tolerance_m=tolerance_m, target=local,
                             approximation_m=sagitta, max_patches=max_patches)
    statuses = {forward['status'], reverse['status']}
    status = 'failed' if 'failed' in statuses else 'passed' if statuses == {'passed'} else 'not_measurable'
    return {'protocol': PROTOCOL, 'status': status, 'passed': status == 'passed',
            'coordinate_space': 'world_metres', 'alignment': 'XY translation only; fixed world Z datum and scale',
            'axis_center_xy_m': center[:2].tolist(), 'tolerance_m': tolerance_m,
            'reference_angular_segments': len(angles), 'reference_sagitta_bound_m': sagitta,
            'candidate_to_analytic': forward, 'analytic_to_candidate': reverse,
            'numeric_guard_m': EPSILON_M,
            'limitations': ['Floating-point bounds with a guard band, not an exact CAD certificate.',
                           'Dimensions, solid topology and full bore occupancy are separate checks.',
                           'The supplied profile and physical datum must come from this case, not candidate metadata.']}
