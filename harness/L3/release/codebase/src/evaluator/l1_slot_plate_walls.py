"""All-triangle radial/axial bounds on the four identified Code014 walls.

Supported straight vertical wall representations are checked at every height,
not sampled planes. Unsupported lean or additional horizontal steps stay
unmeasured. This layer does not replace full shape, topology or preservation.
"""
from __future__ import annotations

import time

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_slot_plate_sections import validate_design


def radial_band(xyz, profile, *, deadline):
    center = np.asarray(profile['center_xy_m'])
    if profile['kind'] == 'slot':
        half = profile['half_length_m']
        axis = shapely.LineString([center+[-half, 0.], center+[half, 0.]])
    else:
        axis = shapely.Point(center)
    minimum, maximum = float('inf'), 0.
    for start in range(0, len(xyz), 256):
        if time.monotonic() >= deadline:
            raise TimeoutError('Whole-wall radial measurement deadline exhausted')
        batch = xyz[start:start+256, :, :2]
        projections = shapely.convex_hull(shapely.multipoints(batch))
        minimum = min(minimum, float(np.min(shapely.distance(projections, axis))))
        maximum = max(maximum, float(np.max(shapely.distance(shapely.points(batch.reshape(-1, 2)), axis))))
    if not len(xyz) or not np.isfinite([minimum, maximum]).all():
        raise ValueError('No finite complete wall band')
    return [minimum, maximum]


def _wall(xyz, profile, nominal_radius, span, tolerance, *, deadline, nominal_length=None):
    normal = np.cross(xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0])
    horizontal_normal = np.linalg.norm(normal[:, :2], axis=1)
    if not len(xyz) or np.any(horizontal_normal == 0):
        return unavailable('Complete expected vertical band unavailable')
    # This is recognition of a straight-wall numerical representation, not
    # an invented physical angle tolerance. Leaning walls require another
    # method; they are not silently projected into vertical ones.
    # Extrapolate each actual face plane over the WHOLE expected layer. Using
    # each triangle's height would let subdivision hide the same tapered wall.
    height = float(span[1]-span[0])
    lean = float(np.max(height*np.abs(normal[:, 2])/horizontal_normal))
    if lean > 2*GUARD:
        return {**unavailable('Nonvertical wall representation needs independent axial treatment'),
                'max_layer_plane_lean_m': lean}
    radius = radial_band(xyz, profile, deadline=deadline)
    checks = {'radial_diameter': interval_check(2*radius[0], 2*radius[1], 2*nominal_radius, tolerance),
        'bottom': interval_check(float(xyz[..., 2].min()), float(xyz[..., 2].min()), float(span[0]), tolerance),
        'top': interval_check(float(xyz[..., 2].max()), float(xyz[..., 2].max()), float(span[1]), tolerance)}
    if nominal_length is not None:
        half = profile['half_length_m']
        checks['total_length_enclosure'] = interval_check(2*half+2*radius[0], 2*half+2*radius[1],
            nominal_length, tolerance, enclosure=True)
    return {**verdict(**checks), 'triangles': len(xyz), 'radius_interval_m': radius,
        'max_layer_plane_lean_m': lean,
        'method': 'Minimum over every projected convex triangle, maximum over all triangle vertices; no height sampling'}


def measure_plate_walls(mesh, design, parameters, topology, *, deadline):
    validate_design(design)
    if type(deadline) not in (int, float) or not np.isfinite(deadline):
        raise ValueError('Finite whole-wall deadline required')
    report = {'protocol': 'l1-slot-plate-whole-walls-v1', 'full_task_verified': False,
        'scope': 'Complete straight-wall radial diameter and axial extents; slot length is an enclosure, not exact extrema'}
    if parameters is None or not topology.get('passed'):
        return {**report, **unavailable('Independent dimensions and separate actual wall patches required')}
    try:
        bounds = np.asarray(parameters['box_bounds_m'])
        plane_guard = float(64*np.finfo(float).eps*max(.1, np.max(np.abs(bounds))))
        checks = {}
        rows = {r['component']: r for r in topology['wall_components']}
        for kind in ('slot', 'hole'):
            for i in range(2):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Whole-wall measurement deadline exhausted')
                key = kind+'_'+str(i)
                owner = topology['passages'][key]['wall_components'][0]
                xyz = mesh.xyz[rows[owner]['source_triangle_ids']]
                horizontal = np.ptp(xyz[..., 2], axis=1) <= plane_guard
                if kind == 'slot':
                    if horizontal.any():
                        checks[key] = unavailable('Additional horizontal slot-wall patch is not a straight extrusion')
                    else:
                        checks[key] = _wall(xyz, parameters['slots'][i], design['slot_radius_m'], bounds[:, 2],
                            design['dimension_tolerance_m'], deadline=deadline,
                            nominal_length=2*(design['slot_half_centers_m']+design['slot_radius_m']))
                    continue
                bore = parameters['bores'][i]
                z = bore['shoulder_z_m']
                if not horizontal.any() or np.max(np.abs(xyz[horizontal, :, 2]-z)) > 2*GUARD:
                    checks[key] = unavailable('Horizontal bore faces are not solely the independently measured shoulder')
                    continue
                sides = xyz[~horizontal]
                low = sides[..., 2].max(axis=1) <= z+2*GUARD
                high = sides[..., 2].min(axis=1) >= z-2*GUARD
                if np.any(low == high):
                    checks[key] = unavailable('Actual bore wall triangles cross an unresolved shoulder boundary')
                    continue
                checks[key] = verdict(
                    lower=_wall(sides[low], bore['lower'], design['hole_radius_m'], [bounds[0, 2], z],
                        design['dimension_tolerance_m'], deadline=deadline),
                    upper=_wall(sides[high], bore['upper'], design['counterbore_radius_m'], [z, bounds[1, 2]],
                        design['dimension_tolerance_m'], deadline=deadline))
        if time.monotonic() >= deadline:
            raise TimeoutError('Whole-wall result missed deadline')
        return {**report, **verdict(**checks)}
    except (ValueError, TimeoutError) as error:
        return {**report, **unavailable(str(error))}
