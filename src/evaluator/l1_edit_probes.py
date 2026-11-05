"""Finite radial surface probes for CodeEdit; no closed-volume claim.

An open but readable surface can be measured. Unreadable/hash-invalid geometry
remains unavailable. Missing intersections on valid surfaces are observations,
not fabricated radii. The frozen section/angle/median policy is unchanged.
"""
from pathlib import Path

import numpy as np

from .l1_surface import load_surface


def ray_distance(xyz, origin, direction):
    e1, e2 = xyz[:, 1]-xyz[:, 0], xyz[:, 2]-xyz[:, 0]
    h = np.cross(direction, e2)
    det = np.einsum('ij,ij->i', e1, h)
    valid = np.abs(det) > np.linalg.norm(e1, axis=1)*np.linalg.norm(e2, axis=1)*1e-12
    inverse = np.divide(1., det, out=np.zeros_like(det), where=valid)
    s = origin-xyz[:, 0]
    u = inverse*np.einsum('ij,ij->i', s, h)
    q = np.cross(s, e1)
    v = inverse*np.einsum('j,ij->i', direction, q)
    distance = inverse*np.einsum('ij,ij->i', e2, q)
    hit = valid & (u >= -1e-9) & (v >= -1e-9) & (u+v <= 1+1e-9) & (distance > 1e-8)
    return float(distance[hit].min()) if hit.any() else None


def measure(payload):
    spec, scene = payload['spec'], payload['scene']
    if 'l1_edit_quality' not in spec:
        raise ValueError('Surface hole probes are scoped to CodeEdit quality')
    root, cache, results = Path(payload['trusted_root']), {}, {}
    for group in spec['checks'].values():
        for check in group:
            if check['metric'] != 'hole_profile' or not check.get('applicable', True):
                continue
            if 'check_ids' in payload and check['id'] not in payload['check_ids']:
                continue
            p = check['params']
            names = p.get('objects', [n for n, o in scene['objects'].items()
                        if o.get('type') == 'MESH' and o.get('visible_render', True)])
            if not names:
                raise ValueError('No inspected surface for hole probe')
            for name in names:
                if name not in cache:
                    cache[name] = load_surface(scene['objects'][name]['mesh_payload'], root, surface_only=True, allow_empty=True)
            surfaces = [cache[n].xyz for n in names if cache[n] is not None]
            xyz = np.concatenate(surfaces) if surfaces else np.empty((0,3,3))
            count, layers = int(p.get('angular_samples', 32)), []
            if count < 1:
                raise ValueError('Positive radial sampling count required')
            for z in p['z_values']:
                origin = np.asarray([*p['center'], z], dtype=float)
                radii = []
                for angle in np.arange(count)*2*np.pi/count:
                    distance = ray_distance(xyz, origin, np.asarray([np.cos(angle), np.sin(angle), 0.]))
                    if distance is not None:
                        radii.append(distance)
                layer = {'z': z, 'radius': None, 'samples': len(radii), 'expected_samples': count}
                if radii:
                    layer.update(radius=sorted(radii)[len(radii)//2], min_radius=min(radii), max_radius=max(radii))
                layers.append(layer)
            tolerance = p['tolerance']
            if isinstance(tolerance, str):
                tolerance = spec['tolerances'][tolerance]
            errors = [abs(row['radius']-p['radius']) for row in layers if row['radius'] is not None]
            results[check['id']] = {'center': [*p['center'], 0.], 'expected_radius': p['radius'],
                'tolerance': tolerance, 'layers': layers, 'max_radius_error': max(errors) if errors else None,
                'through_layers': bool(errors) and len(errors) == len(layers),
                'method': 'world_triangle_radial_surface_sections_v1',
                'scope': 'finite_section_medians_not_closed_solid_or_complete_bore_proof',
                'sources': {n: scene['objects'][n]['mesh_payload']['sha256'] for n in names},
                'surface_diagnostics': {n: cache[n].surface_diagnostics if cache[n] is not None else {'empty_mesh':True} for n in names}}
    return {'probes': results}


def collect(spec, evidence, output, deadline):
    if 'l1_edit_quality' not in spec.to_dict():
        return
    from .l1_compute import run_compute
    from .l1_failures import InspectionFailure, record_failure
    ids = [c.id for group in spec.checks.values() for c in group if c.applicable
           and c.metric == 'hole_profile' and evidence.get('probes', {}).get(c.id) is None]
    if not ids:
        return
    try:
        result = run_compute('edit_hole_profiles', {'spec': spec.to_dict(), 'scene': evidence['scene'],
            'trusted_root': str(output), 'check_ids': ids}, output=output/'edit_probe_jobs', deadline=deadline)
        evidence.setdefault('probes', {}).update(result['probes'])
        evidence['edit_probe_execution'] = result['compute_execution']
    except (InspectionFailure, OSError, KeyError, ValueError) as error:
        failure = error if isinstance(error, InspectionFailure) else InspectionFailure(
            'not_measurable', 'EDIT_PROBES_UNAVAILABLE', str(error))
        record_failure(spec, evidence, ['/probes/'+key for key in ids], failure)
