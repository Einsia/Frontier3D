"""Continuous protected-surface bounds outside a fixed world-space cylinder.

Convex clipping partitions whole triangles. Near-coplanar target triangles are
covered by a union of certified small neighbourhoods, not a convex hull across
holes. Other patches use convex-triangle bounds with adaptive subdivision.
Unknown/budget exhaustion never constitutes preservation.
"""
from __future__ import annotations

import numpy as np
import shapely
from shapely.errors import GEOSException

from .l1_revolution import (
    EPSILON_M,
    convex_patch_neighbors,
    subdivide,
    triangle_to_mesh_upper,
)
from .l1_sections import _projected_radial_min
from .l1_surface import surface_distances

PROTOCOL = 'l1-protected-surface-bounds-v1'


def split_polygon(polygon, normal, offset):
    """Partition a convex polygon by dot(point, normal) <= offset."""
    inside, outside = [], []
    for p, q in zip(polygon, np.roll(polygon, -1, axis=0), strict=True):
        dp, dq = float(p @ normal - offset), float(q @ normal - offset)
        (inside if dp <= 0 else outside).append(p)
        if (dp <= 0) != (dq <= 0):
            point = p + dp/(dp-dq)*(q-p)
            inside.append(point)
            outside.append(point)
    return np.asarray(inside), np.asarray(outside)


def subtract_convex(polygon, planes):
    """Disjoint convex pieces outside a convex intersection of half-spaces."""
    remaining = np.asarray(polygon)
    pieces = []
    for normal, offset in planes:
        if len(remaining) < 3:
            break
        values = remaining @ normal-offset
        if np.max(values) <= 0:
            continue
        if np.min(values) > 0:
            pieces.append(remaining)
            remaining = np.empty((0, remaining.shape[1]))
            break
        remaining, outside = split_polygon(remaining, normal, offset)
        if len(outside) >= 3:
            pieces.append(outside)
    return pieces


def triangulate(polygon):
    return [np.asarray((polygon[0], polygon[i], polygon[i+1])) for i in range(1, len(polygon)-1)]


def cylinder_planes(center_xy, radius, span, sides=128):
    # Inscribed prism is a SUBSET of the allowed analytic cylinder. Removing
    # it retains every truly protected point; it may conservatively retain
    # some allowed points too. Such points can never be rejection witnesses.
    angles = (np.arange(sides)+.5)*2*np.pi/sides
    normals = np.column_stack((np.cos(angles), np.sin(angles), np.zeros(sides)))
    center = np.asarray([*center_xy, 0.])
    support = radius*np.cos(np.pi/sides)
    return [(n, float(n @ center+support)) for n in normals] + [
        (np.array([0., 0., -1.]), -span[0]), (np.array([0., 0., 1.]), span[1])]


def protected_triangles(mesh, center_xy, radius, span, *, sides=128):
    planes = cylinder_planes(center_xy, radius, span, sides)
    pieces = []
    center = np.asarray([*center_xy, 0.])
    for triangle in mesh.xyz:
        local = triangle-center
        rad = np.linalg.norm(local[:, :2], axis=1)
        if rad.max() < radius*np.cos(np.pi/sides) and triangle[:, 2].min() >= span[0] and triangle[:, 2].max() <= span[1]:
            continue
        if (_projected_radial_min(list(local)) >= radius or triangle[:, 2].max() < span[0]
                or triangle[:, 2].min() > span[1]):
            pieces.append(triangle)
        else:
            for polygon in subtract_convex(triangle, planes):
                pieces.extend(triangulate(polygon))
    return np.asarray(pieces).reshape(-1, 3, 3)


def outside_allowed(points, center_xy, radius, span):
    return ((np.linalg.norm(points[:, :2]-center_xy, axis=1) > radius+EPSILON_M)
            | (points[:, 2] < span[0]-EPSILON_M) | (points[:, 2] > span[1]+EPSILON_M))


def near_planar_cover(triangle, target, tolerance, *, cache=None):
    """Prove an ENTIRE source triangle is near a union of actual target faces.

    A target face within t/3 of the source plane is projected onto that plane.
    Its Minkowski sum with an INSCRIBED 8-gon of radius t/3 lies within t/3
    of that projection. Thus a covered point is within sqrt(2)*t/3 in 3D.
    A union of these individual neighbourhoods cannot bridge missing geometry
    beyond that distance. No grid snapping or residual-area cutoff is used.
    Canonical planes are cached; their source projection error is <= EPSILON_M.
    """
    effective = tolerance-32*EPSILON_M
    if effective <= 0:
        return False, 0
    normal = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    norm = np.linalg.norm(normal)
    if norm <= 1e-24:
        return False, 0
    normal /= norm
    if normal[np.argmax(np.abs(normal))] < 0:
        normal = -normal
    normal = np.round(normal, 10)
    normal /= np.linalg.norm(normal)
    offset = round(float(triangle[0] @ normal), 12)
    if np.max(np.abs(triangle @ normal-offset)) > EPSILON_M:
        return False, 0
    key = (*normal, offset)
    cache = {} if cache is None else cache
    try:
        if key not in cache:
            if len(cache) >= 512:
                return False, 0
            axis = np.eye(3)[np.argmin(np.abs(normal))]
            x = np.cross(axis, normal)
            x /= np.linalg.norm(x)
            basis = np.column_stack((x, np.cross(normal, x)))
            origin = normal*offset
            selected = np.max(np.abs(target.xyz @ normal-offset), axis=1) <= effective/3
            near = target.xyz[selected]
            if not len(near):
                cache[key] = (origin, basis, None, 0)
            else:
                projected = (near-origin) @ basis
                angles = np.arange(8)*2*np.pi/8
                padding = np.column_stack((np.cos(angles), np.sin(angles)))*(effective/3)
                points = (projected[:, :, None]+padding).reshape(-1, 24, 2)
                hulls = shapely.convex_hull(shapely.multipoints(points))
                union = shapely.union_all(hulls, grid_size=0)
                if not union.is_valid:
                    return False, len(near)
                shapely.prepare(union)
                cache[key] = (origin, basis, union, len(near))
        origin, basis, union, count = cache[key]
        return (bool(union.covers(shapely.Polygon((triangle-origin) @ basis))) if union is not None else False), count
    except GEOSException:
        return False, 0


def directed_protected(source, target, *, center_xy, radius, span, tolerance,
                       max_patches=65536, max_depth=10):
    pending = protected_triangles(source, center_xy, radius, span)
    original_area = float(np.linalg.norm(np.cross(pending[:, 1]-pending[:, 0], pending[:, 2]-pending[:, 0]), axis=1).sum()/2)
    report = {'status': 'not_measurable', 'passed': False, 'processed_patches': 0,
              'protected_area_conservative_m2': original_area, 'planar_union_proofs': 0,
              'continuous_upper_bound_m': None, 'witness_lower_bound_m': 0.,
              'source_triangles': len(source.xyz), 'clipped_triangles': len(pending)}
    if not len(pending):
        return {**report, 'reason': 'No protected surface to compare'}
    patches = convex_patch_neighbors(target)
    planar_cache = {}
    proved_upper = 0.
    for depth in range(max_depth+1):
        unresolved = []
        for start in range(0, len(pending), 128):
            batch = pending[start:start+128]
            report['processed_patches'] += len(batch)
            if report['processed_patches'] > max_patches:
                return {**report, 'reason': 'Protected surface patch budget exhausted'}
            upper = triangle_to_mesh_upper(batch, target, patches)
            # Clipping may produce collapsed or extremely small fragments.
            # Do not discard them by area: distance-to-surface is 1-Lipschitz,
            # so exact centroid distance + patch radius bounds every point.
            centers = batch.mean(axis=1)
            radii = np.linalg.norm(batch-centers[:, None], axis=2).max(axis=1)
            tiny = radii < tolerance/2
            if tiny.any():
                upper[tiny] = np.minimum(upper[tiny], surface_distances(centers[tiny], target)+radii[tiny])
            accepted = upper < tolerance-EPSILON_M
            if accepted.any():
                proved_upper = max(proved_upper, float(upper[accepted].max()))
            for triangle in batch[~accepted]:
                # Only a point OUTSIDE the true allowed cylinder may reject.
                points = np.concatenate((triangle, triangle.mean(axis=0, keepdims=True)))
                points = points[outside_allowed(points, np.asarray(center_xy), radius, span)]
                if len(points):
                    distances = surface_distances(points, target)
                    lower = float(distances.max())
                    report['witness_lower_bound_m'] = max(report['witness_lower_bound_m'], lower)
                    if lower > tolerance+EPSILON_M:
                        return {**report, 'status': 'failed', 'reason': 'Protected surface changed beyond serialization tolerance',
                                'witness_world_m': points[int(np.argmax(distances))].tolist()}
                covered, _ = near_planar_cover(triangle, target, tolerance, cache=planar_cache)
                if covered:
                    proved_upper = max(proved_upper, np.sqrt(2)*(tolerance-32*EPSILON_M)/3+EPSILON_M)
                    report['planar_union_proofs'] += 1
                else:
                    unresolved.append(triangle)
        if not unresolved:
            return {**report, 'status': 'passed', 'passed': True, 'depth': depth,
                    'continuous_upper_bound_m': proved_upper}
        if report['processed_patches']+4*len(unresolved) > max_patches:
            break
        pending = subdivide(np.asarray(unresolved))
    return {**report, 'reason': 'Unresolved protected surface at subdivision/depth limit',
            'unresolved_examples_world_m': [t.tolist() for t in unresolved[:3]]}


def compare_protected_surfaces(candidate, baseline, *, center_xy, radius, span, tolerance,
                               max_patches=65536):
    if (len(center_xy) != 2 or len(span) != 2
            or not np.isfinite([*center_xy, radius, *span, tolerance]).all()
            or radius <= 0 or span[0] >= span[1] or tolerance <= 32*EPSILON_M
            or type(max_patches) is not int or not 1 <= max_patches <= 1048576):
        raise ValueError('Invalid protected-surface cylinder or precision')
    forward = directed_protected(candidate, baseline, center_xy=center_xy, radius=radius,
                                 span=span, tolerance=tolerance, max_patches=max_patches)
    reverse = directed_protected(baseline, candidate, center_xy=center_xy, radius=radius,
                                 span=span, tolerance=tolerance, max_patches=max_patches)
    for direction in (forward, reverse):
        direction['changed_area_above_tolerance_m2_bounds'] = [0., (
            0. if direction['status'] == 'passed' else direction['protected_area_conservative_m2'])]
        direction['changed_area_method'] = ('Whole protected surface certified within tolerance' if direction['status'] == 'passed'
            else 'Unlocalized conservative area interval; a point witness is not an area estimate')
    states = {forward['status'], reverse['status']}
    status = 'failed' if 'failed' in states else 'passed' if states == {'passed'} else 'not_measurable'
    return {'protocol': PROTOCOL, 'status': status, 'passed': status == 'passed',
            'alignment': 'none; original world metres', 'preservation_tolerance_m': tolerance,
            'allowed_edit': {'center_xy_m': list(center_xy), 'radius_m': radius, 'span_m': list(span),
                             'clipping': 'conservative inscribed 128-sided prism; rejected witnesses outside analytic cylinder'},
            'candidate_to_baseline': forward, 'baseline_to_candidate': reverse,
            'limitations': ['Floating-point guarded bounds, not exact arithmetic CAD certificates',
                           'Inscribed edit-boundary overcoverage may stay unmeasurable near tolerance',
                           'Surface preservation does not itself report volume symmetric difference']}
