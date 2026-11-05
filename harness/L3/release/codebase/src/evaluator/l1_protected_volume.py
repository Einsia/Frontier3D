"""Diagnostic solid symmetric difference outside a world-space edit cylinder.

This is a floating-point Boolean measurement, NOT a certified volume gate.
Inscribed/circumscribed cutters bracket the analytic allowed region; the
reported interval brackets polygonal clipping error, not solver roundoff.
"""
from importlib.metadata import version

import manifold3d as manifold
import numpy as np


def _solid(mesh):
    solid = manifold.Manifold(manifold.Mesh64(
        np.array(mesh.vertices, dtype=np.float64, order='C', copy=True),
        np.array(mesh.triangles, dtype=np.uint64, order='C', copy=True)))
    if solid.status() != manifold.Error.NoError or solid.volume() <= 0:
        raise ValueError('Boolean backend rejected the independently validated solid')
    xyz = mesh.xyz-mesh.vertices.mean(axis=0)
    signed = float(np.einsum('ij,ij->i', xyz[:, 0], np.cross(xyz[:, 1], xyz[:, 2])).sum()/6)
    if signed <= 0 or abs(solid.volume()-signed) > max(1e-18, signed*1e-8):
        raise ValueError('Boolean input volume disagrees with original oriented triangles')
    return solid


def protected_volume(candidate, baseline, *, center_xy, radius, span, precision_m,
                     solid_validated, segments=256):
    report = {'protocol': 'l1-protected-volume-diagnostic-v1', 'status': 'not_measurable',
              'hard_gate': False, 'alignment': 'none; original world metres',
              'backend': 'manifold3d', 'backend_version': version('manifold3d'),
              'cutter_segments': segments, 'not_assessed': ['certified_solver_roundoff',
                  'calibrated_volume_acceptance_threshold']}
    if not solid_validated:
        return {**report, 'reason': 'Independently validated closed solids required'}
    if (len(center_xy) != 2 or len(span) != 2 or span[1] <= span[0]
            or not np.isfinite([*center_xy, radius, *span, precision_m]).all()
            or radius <= 0 or precision_m <= 0 or type(segments) is not int or not 32 <= segments <= 4096):
        raise ValueError('Invalid protected-volume region')
    try:
        a, b = _solid(candidate), _solid(baseline)
        if max(a.get_tolerance(), b.get_tolerance()) > precision_m/100:
            raise ValueError('Boolean input precision insufficient for preservation analysis')
        removed, added = b-a, a-b
        rows = []
        for outer in (False, True):
            r = radius/np.cos(np.pi/segments) if outer else radius
            cutter = manifold.Manifold.cylinder(span[1]-span[0], r, circular_segments=segments)
            cutter = cutter.translate([*center_xy, span[0]])
            pieces = [added-cutter, removed-cutter]
            if any(p.status() != manifold.Error.NoError for p in pieces):
                raise ValueError('Protected volume Boolean operation failed')
            values = [p.volume() for p in pieces]
            if not np.isfinite(values).all() or min(values) < 0:
                raise ValueError('Invalid protected-volume result')
            rows.append({'cutter': 'circumscribed' if outer else 'inscribed',
                         'radius_m': float(r), 'added_m3': values[0], 'removed_m3': values[1],
                         'symmetric_difference_m3': sum(values),
                         'solver_tolerance_m': max(p.get_tolerance() for p in pieces)})
        lower, upper = rows[1]['symmetric_difference_m3'], rows[0]['symmetric_difference_m3']
        if lower > upper+max(1e-18, max(a.volume(), b.volume())*1e-8):
            raise ValueError('Inscribed/circumscribed cutter volumes violate set inclusion')
        report.update(status='measured', candidate_volume_m3=a.volume(), baseline_volume_m3=b.volume(),
                      full_symmetric_difference_m3=added.volume()+removed.volume(),
                      protected_difference_clip_interval_m3=[min(lower, upper), max(lower, upper)],
                      clipping=rows, input_solver_tolerance_m=max(a.get_tolerance(), b.get_tolerance()))
    except (ValueError, RuntimeError) as error:
        report['reason'] = str(error)
    return report
