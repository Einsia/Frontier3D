"""Case-bound machined sleeve measurements from trusted world-metre triangles.

Text2Code 013 has a completely specified revolved polygon, not a reference
image or a scene-semantic target. The surface bound, independent dimensions,
annular shoulder connectivity and full bore occupancy are separate tests.
Planar annuli/cylindrical bands that cannot be identified stay unmeasured.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np

from .l1_revolution import EPSILON_M, compare_revolution
from .l1_sections import (
    _projected_radial_min,
    circle_boundary,
    measure_bore,
    section_loops,
)
from .l1_surface import SurfaceMesh, load_surface

PROTOCOL = 'l1-machined-sleeve-v1'
FIELDS = {'outer_radius_m', 'bore_radius_m', 'height_m', 'groove_width_m',
          'groove_depth_m', 'groove_center_z_m', 'chamfer_m', 'tolerance_m'}
FEATURES = {'solid', 'surface', 'body_dimensions', 'through_bore', 'groove', 'chamfers'}
GUARD = 8*EPSILON_M


def validate_design(design):
    if not isinstance(design, dict) or set(design) != FIELDS:
        raise ValueError('Sleeve design requires explicit case dimensions and tolerance')
    if any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0 for v in design.values()):
        raise ValueError('Sleeve dimensions must be finite positive numbers')
    r, b, h, w, d, z, c, t = (design[k] for k in (
        'outer_radius_m', 'bore_radius_m', 'height_m', 'groove_width_m',
        'groove_depth_m', 'groove_center_z_m', 'chamfer_m', 'tolerance_m'))
    if not (4*GUARD < t < min(c, d, w)/4 and b+c < r-c and b < r-d
            and c+4*t < z-w/2 < z+w/2 < h-c-4*t):
        raise ValueError('Unsupported intersecting or undersized sleeve features')


def profile_for(design):
    validate_design(design)
    r, b, h, w, d, z, c = (design[k] for k in (
        'outer_radius_m', 'bore_radius_m', 'height_m', 'groove_width_m',
        'groove_depth_m', 'groove_center_z_m', 'chamfer_m'))
    return np.asarray([(r-c, 0), (r, c), (r, z-w/2), (r-d, z-w/2),
                       (r-d, z+w/2), (r, z+w/2), (r, h-c), (r-c, h),
                       (b+c, h), (b, h-c), (b, c), (b+c, 0)])


def unavailable(reason):
    return {'status': 'not_measurable', 'passed': False, 'reason': reason}


def verdict(**items):
    statuses = {v['status'] for v in items.values()}
    status = 'failed' if 'failed' in statuses else 'passed' if statuses == {'passed'} else 'not_measurable'
    return {'status': status, 'passed': status == 'passed', 'measurements': items}


def interval_check(low, high, expected, tolerance, *, enclosure=False):
    """An enclosing interval must fit inside the physical acceptance interval.

    Here extrema are witnessed on the mesh (radial minima on triangle edges or
    interiors, maxima on vertices). Near the floating guard stays unmeasured.
    """
    error = max(abs(low-expected), abs(high-expected))
    status = 'passed' if error < tolerance-GUARD else 'failed' if error > tolerance+GUARD else 'not_measurable'
    if enclosure and status == 'failed' and not (high < expected-tolerance-GUARD or low > expected+tolerance+GUARD):
        status = 'not_measurable'
    return {'status': status, 'passed': status == 'passed', 'actual_interval_m': [float(low), float(high)],
            'expected_m': expected, 'tolerance_m': tolerance, 'max_error_m': float(error), 'numeric_guard_m': GUARD,
            'interval_kind': 'conservative_enclosure' if enclosure else 'witnessed_extrema'}


def boundary_edges(triangles):
    counts = Counter(tuple(sorted((int(t[i]), int(t[(i+1) % 3])))) for t in triangles for i in range(3))
    if any(count > 2 for count in counts.values()):
        raise ValueError('Nonmanifold feature patch')
    return {edge for edge, count in counts.items() if count == 1}


def radial_interval(xyz):
    return (min(_projected_radial_min(list(t)) for t in xyz),
            float(np.linalg.norm(xyz[..., :2], axis=-1).max()))


def boundary_cycles(edges):
    graph = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    if not graph or any(len(v) != 2 for v in graph.values()):
        raise ValueError('Feature has branched or open boundaries')
    remaining, loops = set(graph), []
    while remaining:
        first = current = min(remaining)
        previous, indices = None, []
        while current in remaining:
            remaining.remove(current)
            indices.append(current)
            nxt = next(v for v in graph[current] if v != previous)
            previous, current = current, nxt
        if current != first or len(indices) < 3:
            raise ValueError('Invalid feature boundary cycle')
        loops.append(indices)
    return loops


def cylinder_band(mesh, radius, zrange, window):
    radii = np.linalg.norm(mesh.xyz[..., :2], axis=-1)
    selected = ((np.ptp(radii, axis=1) <= GUARD)
                & (np.abs(radii.mean(axis=1)-radius) < window)
                & (mesh.centers[:, 2] > zrange[0]) & (mesh.centers[:, 2] < zrange[1]))
    if not selected.any():
        raise ValueError('No measurable cylindrical face band')
    xyz = mesh.xyz[selected]
    edges = boundary_edges(mesh.triangles[selected])
    loops = boundary_cycles(edges)
    if len(loops) != 2 or any(np.ptp(mesh.vertices[indices, 2]) > GUARD for indices in loops):
        raise ValueError('Cylinder band is incomplete; two complete planar ring boundaries required')
    return {'radius_interval_m': radial_interval(xyz),
            'z_interval_m': (float(xyz[..., 2].min()), float(xyz[..., 2].max())),
            'boundary_edges': edges, 'triangles': int(selected.sum())}


def annular_plane(mesh, nominal_z, window):
    selected = ((np.ptp(mesh.xyz[..., 2], axis=1) <= GUARD)
                & (np.abs(mesh.centers[:, 2]-nominal_z) < window))
    xyz = mesh.xyz[selected]
    if not len(xyz) or np.ptp(xyz[..., 2]) > GUARD:
        raise ValueError('A unique planar annular feature could not be measured')
    edges = boundary_edges(mesh.triangles[selected])
    loops = []
    for indices in boundary_cycles(edges):
        points = mesh.vertices[indices]
        # Degenerate triangles are not used here; radial minimum is computed
        # over actual boundary edges, including their interiors.
        radii = np.linalg.norm(points[:, :2], axis=1)
        low = min(_projected_radial_min([a, b]) for a, b in zip(points, np.roll(points, -1, axis=0), strict=True))
        loop_edges = {tuple(sorted((a, b))) for a, b in zip(indices, indices[1:]+indices[:1], strict=True)}
        loops.append({'radius_interval_m': (low, float(radii.max())), 'edges': loop_edges})
    if len(loops) != 2:
        raise ValueError('Expected two closed annular boundaries')
    loops.sort(key=lambda row: row['radius_interval_m'][1])
    return {'z_m': float(xyz[..., 2].mean()), 'inner': loops[0], 'outer': loops[1]}


def measure_sleeve(mesh, design, *, solid_validated, max_patches=262144):
    profile = profile_for(design)
    r, b, h, w, d, z, c, t = (design[k] for k in (
        'outer_radius_m', 'bore_radius_m', 'height_m', 'groove_width_m',
        'groove_depth_m', 'groove_center_z_m', 'chamfer_m', 'tolerance_m'))
    edges = {tuple(sorted((int(t[i]), int(t[(i+1) % 3])))) for t in mesh.triangles for i in range(3)}
    euler = len(mesh.vertices)-len(edges)+len(mesh.triangles)
    solid_pass = bool(solid_validated and euler == 0)
    features = {'solid': {'status': 'passed' if solid_pass else 'failed', 'passed': solid_pass,
                          'euler_characteristic': euler, 'expected_euler_characteristic': 0,
                          'trusted_closed_connected_editable_solid': bool(solid_validated)}}
    result = {'protocol': PROTOCOL, 'design': design, 'features': features,
              'scope': 'Text2Code machined-sleeve numeric geometry; no scene-text semantics',
              'limitations': ['Planar annuli and cylindrical bands must be measurable; unknown is not a pass.',
                             'Dimensions use actual mesh surfaces including polygonal chord error.',
                             'Floating-point guard bands, not an exact CAD certificate.']}
    try:
        section = section_loops(mesh, (0, 0, 0), (0, 0, 1), (z-w/2+c)/2)
        outer = [loop for loop in section.get('loops', []) if loop['kind'] == 'outer']
        if section['status'] != 'ok' or len(outer) != 1:
            raise ValueError('Cannot identify a unique outer axis section')
        fit = circle_boundary(outer[0]['points_m'])
        center = np.asarray(section['basis_world']) @ np.asarray([*fit['center_plane_m'], 0.])
        result['axis_center_xy_m'] = center[:2].tolist()
        local = SurfaceMesh(mesh.vertices-center, mesh.triangles)
    except ValueError as error:
        for name in FEATURES-{'solid'}:
            features[name] = unavailable(str(error))
        return {**result, **{k: v for k, v in verdict(**features).items() if k != 'measurements'}}
    features['surface'] = compare_revolution(local, profile, t, max_patches=max_patches)
    bottom, top = float(local.vertices[:, 2].min()), float(local.vertices[:, 2].max())
    body = {'height': interval_check(top-bottom, top-bottom, h, t),
            'bottom_z': interval_check(bottom, bottom, 0., t)}
    bands = {}
    for name, radius, span in (
        ('lower_body', r, (0, z-w/2)), ('upper_body', r, (z+w/2, h)),
        ('groove', r-d, (z-w, z+w)), ('bore', b, (0, h)),
    ):
        try:
            bands[name] = cylinder_band(local, radius, span, 4*t)
        except ValueError as error:
            bands[name] = unavailable(str(error))
    for name in ('lower_body', 'upper_body'):
        band = bands[name]
        body[name+'_diameter'] = (interval_check(*(2*v for v in band['radius_interval_m']), 2*r, t, enclosure=True)
                                 if 'radius_interval_m' in band else band)
    features['body_dimensions'] = verdict(**body)
    bore = measure_bore(local, (0, 0, 0), (0, 0, 1), (bottom-t, top+t), b, t/2,
                        solid_validated=solid_validated)
    corridor = bore['corridor']
    opening = ('failed' if corridor['boundary_clear'] is False else
               'passed' if bore['through_corridor'] is True else 'not_measurable')
    band = bands['bore']
    features['through_bore'] = verdict(
        continuous_opening={'status': opening, 'passed': opening == 'passed', 'evidence': bore},
        barrel_diameter=(interval_check(*(2*v for v in band['radius_interval_m']), 2*b, t, enclosure=True)
                         if 'radius_interval_m' in band else band))
    planes = {}
    for name, height in (('bottom', 0), ('lower_shoulder', z-w/2), ('upper_shoulder', z+w/2), ('top', h)):
        try:
            planes[name] = annular_plane(local, height, 4*t)
        except ValueError as error:
            planes[name] = unavailable(str(error))
    if all('z_m' in planes[n] for n in ('lower_shoulder', 'upper_shoulder')) and all(
        'radius_interval_m' in bands[n] for n in ('lower_body', 'upper_body', 'groove')):
        lower, upper = planes['lower_shoulder'], planes['upper_shoulder']
        measured_width = upper['z_m']-lower['z_m']
        measured_center = (upper['z_m']+lower['z_m'])/2
        groove = {'width': interval_check(measured_width, measured_width, w, t),
                  'center_z': interval_check(measured_center, measured_center, z, t)}
        for name, plane in (('lower_body', lower), ('upper_body', upper)):
            lo, hi = bands[name]['radius_interval_m']
            glo, ghi = bands['groove']['radius_interval_m']
            groove[name+'_depth'] = interval_check(lo-ghi, hi-glo, d, t, enclosure=True)
            sharp = (plane['inner']['edges'] <= bands['groove']['boundary_edges']
                     and plane['outer']['edges'] <= bands[name]['boundary_edges'])
            groove[name+'_sharp'] = {'status': 'passed' if sharp else 'failed', 'passed': sharp,
                                     'method': 'full_closed_annular_boundaries_shared_with_cylinder_patches'}
        features['groove'] = verdict(**groove)
    else:
        features['groove'] = unavailable('Both planar shoulders and their cylindrical neighbors are required')
    chamfers = {}
    for end, band_name, index in (('bottom', 'lower_body', 0), ('top', 'upper_body', 1)):
        plane = planes[end]
        for side, band_key in (('outer', band_name), ('inner', 'bore')):
            band = bands[band_key]
            key = end+'_'+side
            if 'z_m' not in plane or 'radius_interval_m' not in band:
                chamfers[key] = unavailable('End annulus/cylinder needed to measure chamfer legs')
                continue
            axial = abs(plane['z_m']-band['z_interval_m'][index])
            plo, phi = plane[side]['radius_interval_m']
            blo, bhi = band['radius_interval_m']
            lo, hi = (blo-phi, bhi-plo) if side == 'outer' else (plo-bhi, phi-blo)
            chamfers[key] = verdict(axial_leg=interval_check(axial, axial, c, t),
                                     radial_leg=interval_check(lo, hi, c, t, enclosure=True))
            chamfers[key]['angle_interval_deg'] = np.degrees(np.arctan2([lo, hi], axial)).tolist()
            chamfers[key]['angle_policy'] = '45-degree analytic surface plus both specified 0.9 mm legs; no hidden angle tolerance'
    features['chamfers'] = verdict(**chamfers)
    result.update({k: v for k, v in verdict(**features).items() if k != 'measurements'})
    return result


def inspect_sleeve(scene, design, *, trusted_root, max_patches=262144):
    validate_design(design)
    objects = scene.get('objects', {})
    meshes = [(name, record) for name, record in objects.items()
              if record.get('entity_scope') == 'delivery_geometry' and record.get('type') == 'MESH']
    if len(meshes) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry' for r in objects.values()):
        return {'protocol': PROTOCOL, 'design': design, 'status': 'failed', 'passed': False,
                'features': {name: {'status': 'failed', 'passed': False,
                                   'reason': 'Expected one editable delivery mesh'} for name in FEATURES}}
    name, record = meshes[0]
    mesh = load_surface(record['mesh_payload'], Path(trusted_root))
    valid = (record.get('valid_solid') is True and record.get('closed') is True
             and record.get('components') == 1 and record.get('editable') is True)
    report = measure_sleeve(mesh, design, solid_validated=valid, max_patches=max_patches)
    report['source'] = {'object': name, 'mesh_payload': record['mesh_payload'], 'trusted_solid': valid}
    return report
