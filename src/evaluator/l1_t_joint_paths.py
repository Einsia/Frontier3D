"""Code013 finite circular sections and a connected, continuous empty core.

All sections and corridor obstructions use actual complete triangles in world
metres. Empty cylinders overlap in certified open balls, connecting the five
public flow ports; separate empty ray probes are not a connectivity proof.
This kernel is not yet a scoring gate or complete wall/shape/preservation test.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np
import shapely

from .l1_capsule_corridor import GUARD, capsule_corridor
from .l1_sections import axis_frame, circle_boundary, section_loops
from .l1_sleeve import interval_check, unavailable, verdict
from .l1_surface import SurfaceMesh, load_surface

FIELDS = {'main_outer_radius_m', 'main_inner_radius_m', 'main_height_m',
          'branch_outer_radius_m', 'branch_inner_radius_m', 'branch_end_x_m', 'branch_z_m',
          'socket_radius_m', 'socket_depth_m', 'radial_x_m', 'radial_radius_m',
          'dimension_tolerance_m', 'preservation_tolerance_m'}


def validate_design(design):
    if not isinstance(design, dict) or set(design) != FIELDS:
        raise ValueError('T connector requires the explicit public geometry and tolerances')
    if any(type(v) not in (float, int) or not np.isfinite(v) or v <= 0 for v in design.values()):
        raise ValueError('T connector dimensions must be finite positive numbers')
    d, t, p = design, design['dimension_tolerance_m'], design['preservation_tolerance_m']
    shoulder = d['branch_end_x_m']-d['socket_depth_m']
    if not (32*GUARD < p < t < d['radial_radius_m']/4
            and 4*t < d['main_inner_radius_m'] < d['main_outer_radius_m']-4*t
            and 4*t < d['branch_inner_radius_m'] < d['socket_radius_m']-4*t
            and d['socket_radius_m'] < d['branch_outer_radius_m']-4*t
            and d['branch_outer_radius_m']+4*t < d['branch_z_m']
            < d['main_height_m']-d['branch_outer_radius_m']-4*t
            and d['main_outer_radius_m']+4*d['radial_radius_m'] < d['radial_x_m']
            < shoulder-4*d['radial_radius_m']
            and d['socket_depth_m'] > 4*t):
        raise ValueError('Unsupported T connector geometry or precision')


def circular_section(mesh, center, axis, offset, expected, *, center_tolerance):
    """Measure selected oriented complete loops; expected: kind -> (radius, diameter tolerance)."""
    section = section_loops(mesh, center, axis, offset)
    if section['status'] != 'ok':
        return unavailable(section.get('reason', 'Actual section is unavailable'))
    rows = {}
    for kind, (radius, tolerance) in expected.items():
        matches = []
        for loop in section['loops']:
            polygon = shapely.Polygon(loop['points_m'])
            if polygon.is_empty or not polygon.is_valid:
                return unavailable('Invalid actual section polygon')
            if loop['kind'] == kind and polygon.contains(shapely.Point(0., 0.)):
                matches.append(loop)
        if len(matches) != 1:
            rows[kind] = {'status': 'failed', 'passed': False,
                          'reason': 'No unique oriented section loop at the required axis'}
            continue
        fit = circle_boundary(matches[0]['points_m'])
        lower, upper = fit['min_boundary_radius_m'], fit['max_boundary_radius_m']
        center_error = float(np.linalg.norm(fit['center_plane_m']))
        rows[kind] = {**verdict(
            diameter=interval_check(2*lower, 2*upper, 2*radius, tolerance),
            center=interval_check(center_error, center_error, 0., center_tolerance)), 'fit': fit}
    return {**verdict(**rows), 'section': section,
            'scope': 'Complete boundary at this finite plane, not full-height dimensions'}


def _corridor(mesh, center, axis, radius, span, **kwargs):
    # Orthogonal frame changes coordinates only, never aligns the candidate.
    if (not kwargs['solid_validated'] or len(mesh.triangles) > kwargs['max_triangles']
            or kwargs['deadline'] is not None and time.monotonic() >= kwargs['deadline']):
        return unavailable('Trusted solid or remaining complete-mesh measurement budget unavailable')
    if span[1]-span[0] <= 4*GUARD:
        return unavailable('Actual asset does not span the required opening interval')
    local = SurfaceMesh((mesh.vertices-np.asarray(center)) @ axis_frame(axis), mesh.triangles)
    return {**capsule_corridor(local, [[0., 0.], [0., 0.]], radius, span, **kwargs),
            'coordinate_space': 'declared_axis_frame_metres', 'center_world_m': list(center),
            'axis_world': list(axis)}


def overlap_ball(a, b, point):
    """An explicit open ball inside both finite open cylinders proves an edge."""
    point = np.asarray(point, dtype=float)
    margins = []
    for tube in (a, b):
        delta = point-np.asarray(tube['center'])
        axis = np.asarray(tube['axis'], dtype=float)
        axis /= np.linalg.norm(axis)
        height = float(delta @ axis)
        radial = float(np.linalg.norm(delta-height*axis))
        margins.append(min(tube['radius']-radial, height-tube['span'][0], tube['span'][1]-height))
    margin = min(margins)-GUARD
    return {'status': 'passed' if margin > GUARD else 'not_measurable', 'passed': margin > GUARD,
            'point_world_m': point.tolist(), 'open_ball_radius_m': max(0., margin)}


def measure_t_joint_paths(mesh, design, *, solid_validated, deadline=None, max_triangles=262144):
    validate_design(design)
    if (type(solid_validated) is not bool or type(max_triangles) is not int or max_triangles <= 0
            or deadline is not None and (type(deadline) not in (int, float) or not np.isfinite(deadline))):
        raise ValueError('Invalid trusted solid flag or T connector budget')
    d, t, p = design, design['dimension_tolerance_m'], design['preservation_tolerance_m']
    z, end, radial, shoulder = d['branch_z_m'], d['branch_end_x_m'], d['radial_x_m'], d['branch_end_x_m']-d['socket_depth_m']
    requests = []
    for name, height in [('main_lower', (z-d['branch_outer_radius_m'])/2),
                         ('main_upper', (z+d['branch_outer_radius_m']+d['main_height_m'])/2)]:
        requests.append((name, [0., 0., 0.], [0., 0., 1.], height,
                         {'outer': (d['main_outer_radius_m'], 2*p), 'cavity': (d['main_inner_radius_m'], 2*p)}, p))
    for name, offset, inner in [('branch_before_holes', (d['main_outer_radius_m']+radial-d['radial_radius_m'])/2, d['branch_inner_radius_m']),
                                ('branch_after_holes', (radial+d['radial_radius_m']+shoulder)/2, d['branch_inner_radius_m']),
                                ('socket', (shoulder+end)/2, d['socket_radius_m'])]:
        requests.append((name, [0., 0., z], [1., 0., 0.], offset,
                         {'outer': (d['branch_outer_radius_m'], t), 'cavity': (inner, t)}, t))
    for sign in (-1, 1):
        offset = sign*(d['branch_inner_radius_m']+d['branch_outer_radius_m'])/2
        requests.append(('radial_'+str(sign), [radial, 0., z], [0., 1., 0.], offset,
                         {'cavity': (d['radial_radius_m'], t)}, t))
    sections = {}
    for name, center, axis, offset, expected, tolerance in requests:
        if not solid_validated:
            measured = unavailable('Trusted closed oriented connected solid required')
        elif deadline is not None and time.monotonic() >= deadline or len(mesh.triangles) > max_triangles:
            measured = unavailable('Section measurement budget exhausted')
        else:
            measured = circular_section(mesh, center, axis, offset, expected, center_tolerance=tolerance)
            if deadline is not None and time.monotonic() >= deadline:
                measured = unavailable('Section measurement exceeded deadline')
        sections[name] = measured
    low, high = mesh.vertices.min(axis=0), mesh.vertices.max(axis=0)
    # Inset cores tolerate independent diameter/position variation. They prove
    # communication and reject separating membranes, not complete wall shape.
    tubes = {
        'main': {'center': [0., 0., 0.], 'axis': [0., 0., 1.], 'radius': d['main_inner_radius_m']-2*t,
                 'span': [float(low[2]-t), float(high[2]+t)]},
        'branch': {'center': [0., 0., z], 'axis': [1., 0., 0.], 'radius': d['branch_inner_radius_m']-2*t,
                   'span': [-t, float(high[0]+t)]},
        'radial': {'center': [radial, 0., z], 'axis': [0., 1., 0.], 'radius': d['radial_radius_m']-2*t,
                   'span': [float(low[1]-t), float(high[1]+t)]},
        'socket': {'center': [0., 0., z], 'axis': [1., 0., 0.], 'radius': d['socket_radius_m']-2*t,
                   # Depth is relative to the actual end, not the world-X
                   # nominal end. Independent legal end/depth deviations
                   # must not combine into a hidden stricter shoulder gate.
                   'span': [float(high[0]-d['socket_depth_m']+t), float(high[0]+t)]},
    }
    corridors = {name: _corridor(mesh, **tube, solid_validated=solid_validated,
                    deadline=deadline, max_triangles=max_triangles) for name, tube in tubes.items()}
    edges = {}
    for a, b, point in [('main', 'branch', [0., 0., z]), ('branch', 'radial', [radial, 0., z]),
                         ('branch', 'socket', [sum(tubes['socket']['span'])/2, 0., z])]:
        edge = overlap_ball(tubes[a], tubes[b], point)
        if not (corridors[a]['passed'] and corridors[b]['passed']):
            edge = {**edge, **unavailable('Both incident complete cores must first be proved empty')}
        edges[a+'__'+b] = edge
    connectivity = verdict(empty_cores=verdict(**corridors), overlaps=verdict(**edges))
    return {'protocol': 'l1-t-joint-paths-v1', 'design': copy.deepcopy(design),
            'sections': verdict(**sections), 'continuous_communication': connectivity,
            'cores': tubes, 'ports': ['main_bottom', 'main_top', 'branch_end', 'radial_negative', 'radial_positive'],
            'full_task_verified': False, 'formal_score_eligible': False,
            'pending': ['Full wall dimensions and shoulder depth/flatness',
                        'Complete target and initial-surface preservation, material and pose',
                        'Candidate source binding, native/GLB jobs, all seeds and calibration']}


def inspect_t_joint_paths(scene, design, *, trusted_root, deadline=None):
    """Load hash-bound inspector output only, not submission-authored facts."""
    validate_design(design)
    rows = [(name, row) for name, row in scene.get('objects', {}).items()
            if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
    if len(rows) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry'
                             for r in scene.get('objects', {}).values()):
        raise ValueError('Code013 requires one actual editable delivery mesh')
    name, row = rows[0]
    if not {'valid_solid', 'closed', 'components', 'editable', 'mesh_payload'} <= row.keys():
        raise ValueError('Missing trusted solid evidence')
    valid = row['valid_solid'] is True and row['closed'] is True and row['components'] == 1 and row['editable'] is True
    mesh = load_surface(row['mesh_payload'], Path(trusted_root))
    result = measure_t_joint_paths(mesh, design, solid_validated=valid, deadline=deadline)
    result['source'] = {'object': name, 'mesh_payload': copy.deepcopy(row['mesh_payload']), 'trusted_solid': valid}
    return result
