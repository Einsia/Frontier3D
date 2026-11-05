"""CodeEdit014 actual obround/counterbore sections and continuous empty paths.

This stage measures finite dimensions independently of complete corridor
emptiness. It does NOT yet certify full-height wall shape, planar shoulders,
old-slot filling, protected surfaces, materials or whole task completion.
No score/metric registration or task activation occurs in this module.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD, capsule_corridor
from .l1_sections import circle_boundary, section_loops
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_surface import load_surface

FIELDS = {'box_size_m', 'slot_rows_y_m', 'slot_half_centers_m', 'slot_radius_m',
          'hole_centers_xy_m', 'hole_radius_m', 'counterbore_radius_m',
          'counterbore_depth_m', 'dimension_tolerance_m', 'preservation_tolerance_m'}


def validate_design(design):
    if not isinstance(design, dict) or set(design) != FIELDS:
        raise ValueError('Slot plate requires explicit case dimensions and distinct tolerances')
    sizes = {}
    for name, shape in [('box_size_m', (3,)), ('slot_rows_y_m', (2,)), ('hole_centers_xy_m', (2, 2))]:
        value = np.asarray(design[name])
        if value.shape != shape or value.dtype.kind not in 'if' or not np.isfinite(value).all():
            raise ValueError('Invalid plate coordinate array')
        sizes[name] = value.astype(float)
    scalar = [design[k] for k in FIELDS-sizes.keys()]
    if (any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0 for v in scalar)
            or min(sizes['box_size_m']) <= 0):
        raise ValueError('Plate dimensions and precision must be finite positive numbers')
    a, r, hole, counter, depth, t, p = [design[k] for k in ('slot_half_centers_m', 'slot_radius_m',
        'hole_radius_m', 'counterbore_radius_m', 'counterbore_depth_m', 'dimension_tolerance_m',
        'preservation_tolerance_m')]
    x, y, h = sizes['box_size_m']
    if not (32*GUARD < p < t < min(r, hole, depth, h-depth)/4 and a > 4*t
            and hole+4*t < counter and a+r+t < x/2
            and abs(sizes['slot_rows_y_m'][1]-sizes['slot_rows_y_m'][0]) > 2*r+4*t
            and max(abs(sizes['slot_rows_y_m']))+r+t < y/2):
        raise ValueError('Unsupported plate geometry or precision')
    regions = [shapely.LineString([[-a, row], [a, row]]).buffer(r+2*t, quad_segs=64)
               for row in sizes['slot_rows_y_m']]
    regions += [shapely.Point(c).buffer(counter+2*t, quad_segs=64) for c in sizes['hole_centers_xy_m']]
    box = shapely.box(-x/2, -y/2, x/2, y/2)
    if any(not box.contains(region) for region in regions) or any(
            regions[i].intersects(regions[j]) for i in range(4) for j in range(i)):
        raise ValueError('Overlapping or out-of-body required passages')


def profiles(design, upper, *, datum_xy=(0., 0.)):
    a, r = design['slot_half_centers_m'], design['slot_radius_m']
    dx, dy = datum_xy
    rows = [{'id': 'slot_'+str(i), 'kind': 'slot', 'center': [dx, y+dy], 'radius': r,
             'axis': shapely.LineString([[-a+dx, y+dy], [a+dx, y+dy]])} for i, y in enumerate(design['slot_rows_y_m'])]
    radius = design['counterbore_radius_m'] if upper else design['hole_radius_m']
    rows += [{'id': 'hole_'+str(i), 'kind': 'circle', 'center': (np.asarray(c)+datum_xy).tolist(), 'radius': radius,
              'axis': shapely.Point(np.asarray(c)+datum_xy)} for i, c in enumerate(design['hole_centers_xy_m'])]
    return rows


def _profile_check(polygon, profile, design):
    points = np.asarray(polygon.exterior.coords)[:-1]
    tolerance = design['dimension_tolerance_m']
    lower, upper = points.min(axis=0), points.max(axis=0)
    expected_center = np.asarray(profile['center'])
    center = (lower+upper)/2
    checks = {name: interval_check(float(center[i]), float(center[i]), float(expected_center[i]), tolerance)
              for i, name in enumerate(('center_x', 'center_y'))}
    if profile['kind'] == 'slot':
        for axis, name, expected in [(0, 'total_length', 2*(design['slot_half_centers_m']+profile['radius'])),
                                      (1, 'width', 2*profile['radius'])]:
            value = float(upper[axis]-lower[axis])
            checks[name] = interval_check(value, value, expected, tolerance)
        measured_radius = float((upper[1]-lower[1])/2)
        half = float(((upper[0]-lower[0])-(upper[1]-lower[1]))/2)
        if half <= 0:
            checks['capsule_axis'] = {'status': 'failed', 'passed': False,
                                       'reason': 'Measured opening has no positive X-directed capsule segment'}
            return verdict(**checks)
        for sign in (-1, 1):
            value = float(center[0]+sign*half)
            checks['end_center_x_'+str(sign)] = interval_check(value, value,
                float(expected_center[0]+sign*design['slot_half_centers_m']), tolerance)
        measured_axis = shapely.LineString([[center[0]-half, center[1]], [center[0]+half, center[1]]])
        measured_profile = {'kind': 'slot', 'center_xy_m': center.tolist(),
                            'half_length_m': half, 'radius_m': measured_radius}
    else:
        fitted = circle_boundary(points)
        checks['diameter'] = interval_check(2*fitted['min_boundary_radius_m'],
            2*fitted['max_boundary_radius_m'], 2*profile['radius'], tolerance)
        for i, name in enumerate(('fitted_center_x', 'fitted_center_y')):
            value = fitted['center_plane_m'][i]
            checks[name] = interval_check(value, value, float(expected_center[i]), tolerance)
        measured_axis = shapely.Point(fitted['center_plane_m'])
        measured_radius = fitted['radius_m']
        measured_profile = {'kind': 'circle', 'center_xy_m': fitted['center_plane_m'], 'radius_m': measured_radius}
    # Entire line-to-finite-axis minimum and vertex maximum bound every point
    # of every affine section edge. This is representation variation, not a
    # new tolerance: the independent public dimensions still gate the profile.
    measured_profile['boundary_radius_interval_m'] = [
        min(float(polygon.boundary.distance(measured_axis)), float(measured_radius)),
        max(float(np.max(shapely.distance(shapely.points(points), measured_axis))), float(measured_radius))]
    # Polygonal chords approximate the analytic circle/capsule with a known
    # Hausdorff bound. Two complete line covers plus that bound prove proximity;
    # absence of this sufficient proof is not itself a rejection witness.
    # Use the measured centre/dimensions for the SHAPE test, after checking
    # each against its public tolerance. Combining two individually legal
    # deviations into a stricter nominal-surface error would be a hidden gate.
    reference = measured_axis.buffer(measured_radius, quad_segs=128).boundary
    approximation = measured_radius*(1-np.cos(np.pi/512))
    radius = tolerance-approximation-GUARD
    covered = (polygon.boundary.buffer(radius, quad_segs=16).covers(reference)
               and reference.buffer(radius, quad_segs=16).covers(polygon.boundary))
    witnesses = float(np.max(shapely.distance(shapely.points(points), reference)))
    status = 'passed' if covered else 'failed' if witnesses-approximation > tolerance+GUARD else 'not_measurable'
    checks['complete_section_boundary'] = {'status': status, 'passed': status == 'passed',
        'reference_chord_error_bound_m': float(approximation),
        'measured_profile_radius_m': float(measured_radius),
        'candidate_vertex_distance_lower_bound_m': max(0., witnesses-approximation-GUARD),
        'scope': 'Both complete lines against the measured profile; independent public dimension gates above'}
    return {**verdict(**checks), 'measured_profile': measured_profile}


def measure_layer(mesh, design, z_m, upper):
    section = section_loops(mesh, (0., 0., 0.), (0., 0., 1.), z_m)
    if section['status'] != 'ok':
        return unavailable(section.get('reason', 'Section reconstruction unavailable'))
    polygons, outer = [], []
    for loop in section['loops']:
        xyz = np.asarray(loop['points_m']) @ np.asarray(section['basis_world'])[:, :2].T
        polygon = shapely.Polygon(xyz[:, :2])
        if not polygon.is_valid or polygon.is_empty:
            return unavailable('Invalid actual section polygon')
        (polygons if loop['kind'] == 'cavity' else outer).append(polygon)
    topology = len(outer) == 1 and len(polygons) == 4 and all(outer[0].contains(p) for p in polygons)
    datum = (mesh.vertices[:, :2].min(axis=0)+mesh.vertices[:, :2].max(axis=0))/2
    report = {'requested_z_m': z_m, 'actual_z_m': section['offset_m'], 'upper': upper,
              'plate_center_xy_m': datum.tolist(),
              'outer_loops': len(outer), 'cavity_loops': len(polygons)}
    if not topology:
        return {**report, 'status': 'failed', 'passed': False,
                'reason': 'This plane must have one outer boundary and four independent cavities'}
    checks, used = {}, set()
    for profile in profiles(design, upper, datum_xy=datum):
        matched = [i for i, polygon in enumerate(polygons) if polygon.contains(shapely.Point(profile['center']))]
        if len(matched) != 1 or matched[0] in used:
            checks[profile['id']] = {'status': 'failed', 'passed': False,
                                     'reason': 'No unique separate cavity at the required public centre'}
            continue
        used.add(matched[0])
        checks[profile['id']] = _profile_check(polygons[matched[0]], profile, design)
    return {**report, **verdict(**checks)}


def measure_slot_plate_paths(mesh, design, *, solid_validated, deadline=None, max_triangles=262144):
    validate_design(design)
    if type(solid_validated) is not bool:
        raise ValueError('Trusted solid validation must be boolean')
    if deadline is not None and (type(deadline) not in (float, int) or not np.isfinite(deadline)):
        raise ValueError('Invalid slot plate measurement deadline')
    depth, t = design['counterbore_depth_m'], design['dimension_tolerance_m']
    bottom, top = float(mesh.vertices[:, 2].min()), float(mesh.vertices[:, 2].max())
    datum = (mesh.vertices[:, :2].min(axis=0)+mesh.vertices[:, :2].max(axis=0))/2
    shoulder = top-depth
    layers = {}
    for upper, interval in [(False, (bottom, shoulder)), (True, (shoulder, top))]:
        for fraction in (.125, .375, .625, .875):
            name = ('upper' if upper else 'lower')+'_'+str(fraction)
            z = interval[0]+fraction*(interval[1]-interval[0])
            if not solid_validated:
                result = unavailable('Trusted solid validation required')
            elif deadline is not None and time.monotonic() >= deadline:
                result = unavailable('Section measurement deadline exhausted')
            else:
                result = measure_layer(mesh, design, z, upper)
                if deadline is not None and time.monotonic() >= deadline:
                    result = unavailable('Section measurement exceeded deadline')
            layers[name] = result
    corridors = {}
    for profile in profiles(design, False, datum_xy=datum):
        endpoints = ([[datum[0]-design['slot_half_centers_m'], profile['center'][1]],
                      [datum[0]+design['slot_half_centers_m'], profile['center'][1]]]
                     if profile['kind'] == 'slot' else [profile['center'], profile['center']])
        # A core inset by 2t allows independent centre and diameter tolerances;
        # nominal-radius emptiness would wrongly reject a legal displaced hole.
        # Full wall shape/actual throat size are separate pending checks.
        corridors[profile['id']] = capsule_corridor(mesh, endpoints, profile['radius']-2*t,
            (bottom-t, top+t), solid_validated=solid_validated, deadline=deadline, max_triangles=max_triangles)
    for profile in profiles(design, True, datum_xy=datum)[2:]:
        corridors['counterbore_'+profile['id']] = capsule_corridor(mesh, [profile['center'], profile['center']],
            profile['radius']-2*t, (shoulder+t, top+t), solid_validated=solid_validated,
            deadline=deadline, max_triangles=max_triangles)
    return {'protocol': 'l1-slot-plate-paths-v1', 'design': copy.deepcopy(design),
        'sections': verdict(**layers), 'continuous_empty_paths': verdict(**corridors),
        'relative_datum': {'plate_center_xy_m': datum.tolist(), 'bottom_z_m': bottom, 'top_z_m': top,
                           'world_pose_preservation_checked': False},
        'full_task_verified': False,
        'scope': 'Eight fixed sections and six continuous empty prisms, not all Code014 requirements',
        'pending': ['Full-height wall dimensions and exact shoulder depth/flatness',
                    'Old-slot fill, full target shape and globally separate passages',
                    'Protected surfaces/pose/material and native/GLB/all-seed scoring integration']}


def inspect_slot_plate_paths(scene, design, *, trusted_root, deadline=None):
    """Consume trusted inspector facts; never a candidate-authored scene JSON."""
    validate_design(design)
    objects = scene.get('objects', {})
    rows = [(name, row) for name, row in objects.items()
            if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
    if len(rows) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry' for r in objects.values()):
        raise ValueError('Code014 paths require one actual editable delivery solid')
    name, row = rows[0]
    valid = (row.get('valid_solid') is True and row.get('closed') is True
             and row.get('components') == 1 and row.get('editable') is True)
    mesh = load_surface(row['mesh_payload'], Path(trusted_root))
    result = measure_slot_plate_paths(mesh, design, solid_validated=valid, deadline=deadline)
    result['source'] = {'object': name, 'mesh_payload': copy.deepcopy(row['mesh_payload']), 'trusted_solid': valid}
    return result
