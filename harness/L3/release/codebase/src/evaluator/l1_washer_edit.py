"""CodeEdit 015: actual bore, protected world surface and effective materials.

The reference for preservation is the PUBLIC initial mesh, not a private answer.
No fitted translation/rotation, vertex identity or object names establish a pass.
"""
from pathlib import Path

import numpy as np

from .l1_materials import SCOPES, _equal, _load
from .l1_protected_surface import compare_protected_surfaces
from .l1_protected_volume import protected_volume
from .l1_sections import circle_boundary, measure_bore, section_loops
from .l1_sleeve import (
    GUARD,
    boundary_cycles,
    boundary_edges,
    interval_check,
    radial_interval,
    unavailable,
    verdict,
)
from .l1_surface import SurfaceMesh, load_surface

PROTOCOL = 'l1-washer-edit-v1'
FEATURES = {'solid', 'target_bore', 'protected_surface', 'body_preservation',
            'index_hole', 'material_preservation'}
FIELDS = {'outer_radius_m', 'height_m', 'initial_bore_radius_m', 'bore_radius_m',
          'index_radius_m', 'index_center_xy_m', 'dimension_tolerance_m',
          'preservation_tolerance_m', 'material_tolerance'}


def validate_design(design):
    if not isinstance(design, dict) or set(design) != FIELDS:
        raise ValueError('Washer edit requires explicit target and preservation precision')
    scalar = [design[k] for k in FIELDS-{'index_center_xy_m'}]
    center = design['index_center_xy_m']
    if (not isinstance(center, (list, tuple)) or len(center) != 2
            or any(type(v) not in (int, float) or not np.isfinite(v) for v in [*scalar, *center])
            or min(scalar) <= 0):
        raise ValueError('Invalid washer dimensions/precision')
    r, b, old, small, t, p = (design[k] for k in ('outer_radius_m', 'bore_radius_m',
                            'initial_bore_radius_m', 'index_radius_m',
                            'dimension_tolerance_m', 'preservation_tolerance_m'))
    distance = np.linalg.norm(center)
    if not (32e-9 < p < t/100 and old < b and b+t < distance-small-t
            and distance+small+t < r and t < small/4 and design['material_tolerance'] < 1e-3):
        raise ValueError('Intersecting washer features or unsupported precision')


def _feature_band(mesh, center, radius, height, window):
    local = SurfaceMesh(mesh.vertices-[*center, 0.], mesh.triangles)
    # Boolean cuts insert vertices inside polygonal chord edges. Such vertices
    # legitimately have different radii; equal-radius vertices would reject a
    # correct retriangulation. Bound every selected triangle, then require two
    # complete planar ring boundaries (no omitted sector/branched patch).
    radii = np.linalg.norm(local.xyz[..., :2], axis=-1)
    selected = ((np.max(np.abs(radii-radius), axis=1) < window)
                & (np.ptp(local.xyz[..., 2], axis=1) > GUARD)
                & (local.centers[:, 2] > 0.) & (local.centers[:, 2] < height))
    if not selected.any():
        raise ValueError('No measurable full-height radial face band')
    loops = boundary_cycles(boundary_edges(local.triangles[selected]))
    if len(loops) != 2 or any(np.ptp(local.vertices[loop, 2]) > GUARD for loop in loops):
        raise ValueError('Radial band is incomplete; two full planar rings required')
    xyz = local.xyz[selected]
    return {'radius_interval_m': radial_interval(xyz),
            'z_interval_m': [float(xyz[..., 2].min()), float(xyz[..., 2].max())],
            'triangles': int(selected.sum())}


def _bore(mesh, center, radius, height, tolerance, solid_validated, window):
    bore = measure_bore(mesh, (*center, 0.), (0., 0., 1.),
                        (-tolerance, height+tolerance), radius, tolerance,
                        solid_validated=solid_validated)
    opening = ('failed' if bore['corridor']['boundary_clear'] is False else
               'passed' if bore['through_corridor'] is True else 'not_measurable')
    items = {'continuous_opening': {'status': opening, 'passed': opening == 'passed', 'evidence': bore}}
    try:
        band = _feature_band(mesh, center, radius, height, window)
        low, high = band['radius_interval_m']
        items['radius'] = interval_check(low, high, radius, tolerance)
        items['axial_span'] = verdict(
            bottom=interval_check(*([band['z_interval_m'][0]]*2), 0., tolerance),
            top=interval_check(*([band['z_interval_m'][1]]*2), height, tolerance))
        items['radius']['full_surface_radial_spread_m'] = high-low
    except ValueError as error:
        items['radius'] = unavailable(str(error))
        # The section evidence can reject a demonstrably wrong hole, but
        # section success alone never proves the full cylindrical boundary.
        if bore.get('all_sections_measured') is True and bore.get('radius_within_tolerance') is False:
            items['radius'] = {'status': 'failed', 'passed': False, 'section_evidence': bore}
    return verdict(**items)


def _index_circle(mesh, center, height):
    section = section_loops(mesh, (*center, 0.), (0., 0., 1.), height/2)
    if section['status'] != 'ok':
        raise ValueError('Index-hole section unavailable')
    circles = [circle_boundary(loop['points_m']) for loop in section['loops'] if loop['kind'] == 'cavity']
    if not circles:
        raise ValueError('No cavity boundaries in index-hole section')
    circle = min(circles, key=lambda row: np.linalg.norm(row['center_plane_m']))
    return np.asarray(section['basis_world']) @ np.asarray([*circle['center_plane_m'], 0.])


def uniform_preservation(candidate, baseline, *, trusted_root, scope, tolerance, baseline_root=None):
    """All USED candidate faces must have the public baseline's uniform shader."""
    try:
        if (scope not in SCOPES or type(tolerance) not in (int, float)
                or not np.isfinite(tolerance) or tolerance < 0):
            raise ValueError('Invalid uniform material scope or parameter tolerance')
        _, original = _load(baseline, Path(trusted_root if baseline_root is None else baseline_root), scope)
        _, edited = _load(candidate, Path(trusted_root), scope)
        if len(original) != 1 or original[0]['descriptor']['kind'] != 'constant_principled':
            return unavailable('This pilot requires a uniform constant-Principled public initial material')
        rows = [{'used_slots': group['slots'], 'effective_parameters': group['descriptor'],
                 'passed': _equal(group['descriptor'], original[0]['descriptor'], tolerance)} for group in edited]
        passed = bool(rows) and all(row['passed'] for row in rows)
        return {'status': 'passed' if passed else 'failed', 'passed': passed,
                'scope': scope, 'parameter_tolerance': tolerance,
                'method': 'every_actual_face_assignment_against_uniform_initial_shader',
                'baseline_effective_parameters': original[0]['descriptor'], 'groups': rows}
    except (ValueError, KeyError, OSError, TypeError, IndexError) as error:
        return unavailable(str(error))


def measure_washer(candidate, baseline, design, *, solid_validated, max_patches=65536):
    validate_design(design)
    d = design
    h, r, t, precision = (d[k] for k in ('height_m', 'bore_radius_m', 'dimension_tolerance_m', 'preservation_tolerance_m'))
    features = {'solid': {'status': 'passed' if solid_validated else 'failed', 'passed': bool(solid_validated)}}
    features['target_bore'] = _bore(candidate, (0., 0.), r, h, t, solid_validated,
                                    abs(r-d['initial_bore_radius_m'])+4*t)
    features['protected_surface'] = compare_protected_surfaces(candidate, baseline, center_xy=(0., 0.),
        radius=r+t, span=(-precision, h+precision), tolerance=precision, max_patches=max_patches)
    body = {}
    for axis, name in enumerate(('x', 'y', 'z')):
        for extreme, operation in (('min', np.min), ('max', np.max)):
            actual, expected = (float(operation(mesh.vertices[:, axis])) for mesh in (candidate, baseline))
            body[name+'_'+extreme] = interval_check(actual, actual, expected, precision)
    try:
        band = _feature_band(candidate, (0., 0.), d['outer_radius_m'], h, 4*t)
        body['nominal_outer_diameter'] = interval_check(
            *(2*v for v in band['radius_interval_m']), 2*d['outer_radius_m'], t)
    except ValueError as error:
        body['nominal_outer_diameter'] = unavailable(str(error))
    height = float(np.ptp(candidate.vertices[:, 2]))
    body['nominal_height'] = interval_check(height, height, h, t)
    features['body_preservation'] = verdict(**body)
    index = d['index_center_xy_m']
    small = _bore(candidate, index, d['index_radius_m'], h, t, solid_validated, 4*t)
    try:
        a, b = (_feature_band(mesh, index, d['index_radius_m'], h, 4*t) for mesh in (candidate, baseline))
        for endpoint in (0, 1):
            value, expected = a['radius_interval_m'][endpoint], b['radius_interval_m'][endpoint]
            small['measurements']['preserved_radius_'+str(endpoint)] = interval_check(value, value, expected, precision)
        center_a, center_b = (_index_circle(mesh, index, h) for mesh in (candidate, baseline))
        drift = float(np.linalg.norm(center_a-center_b))
        small['measurements']['preserved_center'] = interval_check(drift, drift, 0., precision)
        small['measurements']['preserved_center']['world_drift_m'] = (center_a-center_b).tolist()
        small = verdict(**small['measurements'])
    except ValueError as error:
        small = verdict(bore=small, preservation=unavailable(str(error)))
    features['index_hole'] = small
    volume = protected_volume(candidate, baseline, center_xy=(0., 0.), radius=r+t,
                              span=(-precision, h+precision), precision_m=precision, solid_validated=solid_validated)
    return {'protocol': PROTOCOL, 'design': design, 'features': features,
            'protected_volume_diagnostic': volume,
            'scope': 'Baseline CodeEdit washer geometry; no whole-task or all-seed completion claim',
            'limitations': ['Protected volume is diagnostic, not a calibrated acceptance gate.',
                           'Nonconstant effective shader equivalence and all-seed checks remain pending.']}


def inspect_washer(scene, baseline, design, *, trusted_root, material_scope, max_patches=65536):
    validate_design(design)
    if material_scope not in SCOPES:
        raise ValueError('Invalid washer material scope')

    def single(scene):
        objects = scene.get('objects', {})
        records = [(name, row) for name, row in objects.items()
                   if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
        if len(records) != 1 or any(row.get('entity_scope') == 'unsupported_delivery_geometry' for row in objects.values()):
            raise ValueError('Expected one actual delivery mesh')
        return records[0]

    def valid(row):
        return (row.get('valid_solid') is True and row.get('closed') is True
                and row.get('components') == 1 and row.get('editable') is True)

    initial_name, initial = single(baseline)
    if not valid(initial):
        raise ValueError('Public initial solid cannot support preservation measurement')
    original = load_surface(initial['mesh_payload'], Path(trusted_root))
    try:
        name, row = single(scene)
    except ValueError as error:
        return {'protocol': PROTOCOL, 'design': design, 'material_scope': material_scope,
                'features': {key: ({'status': 'failed', 'passed': False, 'reason': str(error)}
                                  if key == 'solid' else unavailable(str(error))) for key in FEATURES}}
    if not valid(row):
        return {'protocol': PROTOCOL, 'design': design, 'material_scope': material_scope,
                'status': 'failed', 'passed': False,
                'features': {key: ({'status': 'failed', 'passed': False,
                                  'reason': 'Candidate is not one validated editable closed solid'}
                                  if key == 'solid' else unavailable('Invalid candidate solid')) for key in FEATURES}}
    candidate = load_surface(row['mesh_payload'], Path(trusted_root))
    result = measure_washer(candidate, original, design, solid_validated=valid(row), max_patches=max_patches)
    result['material_scope'] = material_scope
    result['features']['material_preservation'] = uniform_preservation(row, initial,
        trusted_root=trusted_root, scope=material_scope, tolerance=design['material_tolerance'])
    result.update({k: v for k, v in verdict(**result['features']).items() if k != 'measurements'})
    result['source'] = {'object': name, 'baseline_object': initial_name, 'mesh_payload': row['mesh_payload'],
                        'baseline_mesh_payload': initial['mesh_payload'], 'trusted_solid': valid(row)}
    return result
