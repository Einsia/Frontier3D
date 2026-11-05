"""Continuous empty obround prisms from all actual triangles, not z samples.

The footprint is the Euclidean radius-neighbourhood of a finite XY segment.
Each triangle is clipped to the entire Z interval. Its convex projection is
tested against that segment, including interiors and degenerate projections.
Solid winding is meaningful only after trusted solid validation and proof of
no boundary in the connected prism. Floating guard/budget ambiguity stays
unmeasured. This is not a wall-dimension or independent-passage certificate.
"""
from __future__ import annotations

import time

import numpy as np
import shapely

from .l1_sections import _clip_height
from .l1_sleeve import unavailable
from .l1_volume_math import winding_classification

GUARD = 8e-9


def capsule_corridor(mesh, endpoints_xy, radius_m, span_m, *, solid_validated,
                     deadline=None, max_triangles=262144):
    endpoints, span = np.asarray(endpoints_xy, dtype=float), np.asarray(span_m, dtype=float)
    if (endpoints.shape != (2, 2) or not np.isfinite(endpoints).all()
            or span.shape != (2,) or not np.isfinite(span).all() or span[1]-span[0] <= 4*GUARD
            or type(radius_m) not in (float, int) or not np.isfinite(radius_m) or radius_m <= 4*GUARD
            or type(solid_validated) is not bool or type(max_triangles) is not int or max_triangles <= 0
            or deadline is not None and (type(deadline) not in (float, int) or not np.isfinite(deadline))):
        raise ValueError('Invalid capsule corridor, trusted solid flag or budget')
    # Large coordinates need a proportionate round-off allowance. Translation
    # to the same public origin changes neither candidate pose nor dimensions.
    guard = max(GUARD, 256*np.finfo(float).eps*max(1., float(np.abs(mesh.vertices).max()),
                                                    float(np.abs(endpoints).max()), float(np.abs(span).max())))
    report = {'protocol': 'l1-capsule-corridor-v1', 'coordinate_space': 'world_metres',
        'endpoints_xy_m': endpoints.tolist(), 'radius_m': radius_m, 'span_m': span.tolist(),
        'numerical_guard_m': guard, 'triangles_considered': 0, 'intruding_triangles': [],
        'boundary_clear': None, 'empty': None, 'solid_validated': solid_validated,
        'scope': 'Connected empty prism only; not dimensions or separation from other passages'}
    if not solid_validated:
        return {**report, **unavailable('Trusted closed, oriented, connected solid validation required')}
    if radius_m <= 4*guard or span[1]-span[0] <= 4*guard:
        return {**report, **unavailable('Corridor dimensions do not exceed the numerical guard')}
    origin = endpoints.mean(axis=0)
    local = endpoints-origin
    axis = shapely.Point(local[0]) if np.array_equal(local[0], local[1]) else shapely.LineString(local)
    minimum, guarded_minimum = float('inf'), float('inf')
    for index, triangle in enumerate(mesh.xyz):
        if deadline is not None and time.monotonic() >= deadline:
            return {**report, **unavailable('Capsule measurement deadline exhausted')}
        if index >= max_triangles:
            return {**report, **unavailable('Capsule triangle budget exhausted')}
        if triangle[:, 2].max() < span[0]-guard or triangle[:, 2].min() > span[1]+guard:
            continue
        report['triangles_considered'] += 1
        for padding in (0., guard):
            polygon = _clip_height(list(triangle), span[0]-padding, True)
            if polygon:
                polygon = _clip_height(polygon, span[1]+padding, False)
            if not polygon:
                continue
            projected = shapely.MultiPoint(np.asarray(polygon)[:, :2]-origin).convex_hull
            distance = float(projected.distance(axis))
            if not np.isfinite(distance):
                return {**report, **unavailable('Nonfinite projected segment-to-polygon distance')}
            if padding:
                guarded_minimum = min(guarded_minimum, distance)
            else:
                minimum = min(minimum, distance)
                if distance < radius_m-guard:
                    # A genuine boundary point inside the required empty
                    # prism disproves emptiness; no full loop reconstruction.
                    return {**report, 'status': 'failed', 'passed': False,
                            'boundary_clear': False, 'empty': False,
                            'intruding_triangles': [index], 'minimum_distance_m': distance,
                            'reason': 'Actual clipped triangle enters the required empty passage'}
    report.update(minimum_distance_m=None if not np.isfinite(minimum) else minimum,
                  guarded_minimum_distance_m=None if not np.isfinite(guarded_minimum) else guarded_minimum)
    if guarded_minimum <= radius_m+guard:
        return {**report, **unavailable('Boundary is in the capsule numerical guard band')}
    report['boundary_clear'] = True
    if deadline is not None and time.monotonic() >= deadline:
        return {**report, **unavailable('No remaining budget for trusted winding classification')}
    point = np.array([*origin, span.mean()])
    classification = int(winding_classification(mesh.vertices-point, mesh.triangles,
                                                np.zeros((1, 3)), epsilon_m=guard)[0])
    report['winding_probe'] = {'point_world_m': point.tolist(), 'classification': classification}
    if deadline is not None and time.monotonic() >= deadline:
        return {**report, **unavailable('Winding classification exceeded measurement deadline')}
    if classification == -1:
        return {**report, **unavailable('Ambiguous solid occupancy')}
    return {**report, 'status': 'passed' if classification == 0 else 'failed',
            'passed': classification == 0, 'empty': classification == 0,
            'reason': 'All-triangle boundary proof and one connected-region occupancy query'}
