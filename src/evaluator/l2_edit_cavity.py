"""Finite open-top cavity probes; reference regions do not prescribe hidden depth.

Complete triangles determine every vertical hit. The reference identifies the
opening and exposed locations, not a required floor depth, object name or mesh
split. These probes establish a rim above an exposed bottom, not global solidity.
"""
import numpy as np

from .l2_reference_numeric import triangles
from .l2_surface_relief import VerticalSurface, footprint
from .metrics import MissingEvidence


def target_surface(evidence, names):
    selected = [triangles(o, evidence) for n, o in evidence['scene']['objects'].items()
                if n in names and o.get('visible_render') and o.get('faces', 0)]
    if not selected:
        raise MissingEvidence('Complete visible target geometry required')
    return np.concatenate(selected)


def regional_top(evidence, points, ceiling):
    low, high = points.min(0), points.max(0)
    selected = []
    for obj in evidence['scene']['objects'].values():
        if not obj.get('visible_render') or not obj.get('faces', 0):
            continue
        bounds = obj.get('bounds')
        if bounds and (np.any(np.asarray(bounds[1])[:2] < low) or np.any(np.asarray(bounds[0])[:2] > high)):
            continue
        surface = triangles(obj, evidence)
        overlap = (surface[:, :, :2].max(1) >= low).all(1) & (surface[:, :, :2].min(1) <= high).all(1)
        edges = surface[:, 1:] - surface[:, :1]
        overlap &= np.abs(edges[:, 0, 0]*edges[:, 1, 1] - edges[:, 0, 1]*edges[:, 1, 0]) > 1e-14
        if overlap.any():
            selected.append(surface[overlap])
    if not selected:
        return np.full(len(points), np.nan)
    return VerticalSurface(np.concatenate(selected)).top(points, ceiling)


def open_cavity(candidate, baseline, reference, targets):
    before = baseline['scene']['objects']
    ref = target_surface(reference, targets)
    added = set(candidate['scene']['objects']) - before.keys()
    new = target_surface(candidate, added)
    center, radii, rotation = footprint(ref)
    diagonal = float(np.linalg.norm(np.ptp(ref.reshape(-1, 3), axis=0)))
    epsilon = max(diagonal * 1e-7, 1e-7)
    # A numerical nonzero-depth threshold, not the private reference depth.
    min_depth = max(diagonal * 1e-5, 1e-5)
    angles = np.arange(32) * (2 * np.pi / 32)
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    # Search a broad annulus, accommodating round and rectangular openings.
    fractions = np.linspace(.45, 1.05, 61)
    rim_xy = center + (directions[:, None, :] * radii * fractions[None, :, None]) @ rotation.T
    inner_xy = center + (directions[:, None, :] * radii * np.array([.1, .25, .4])[None, :, None]) @ rotation.T
    ref_top, new_top = VerticalSurface(ref), VerticalSurface(new)
    ref_rim = ref_top.top(rim_xy.reshape(-1, 2)).reshape(32, -1)
    new_rim = new_top.top(rim_xy.reshape(-1, 2)).reshape(32, -1)
    ref_rim = np.max(np.where(np.isfinite(ref_rim), ref_rim, -np.inf), axis=1)
    new_rim = np.max(np.where(np.isfinite(new_rim), new_rim, -np.inf), axis=1)
    points = inner_xy.reshape(-1, 2)
    ref_inner = ref_top.top(points)
    # Ignore unrelated room ceilings. Inspect the opening prism through a
    # public margin above the reference rim, rather than the whole sky column.
    opening_ceiling = np.repeat(ref_rim, 3) + .05 * diagonal
    ref_scene = regional_top(reference, points, opening_ceiling)
    ref_depth = np.repeat(ref_rim, 3) - ref_inner
    eligible = np.isfinite(ref_inner) & np.isfinite(ref_depth) & (ref_depth > min_depth)
    eligible &= np.isfinite(ref_scene) & (np.abs(ref_scene - ref_inner) <= epsilon)
    if eligible.sum() < 8 or np.unique(np.flatnonzero(eligible) // 3).size < 8:
        raise MissingEvidence('Reference needs exposed cavity bottom in at least eight directions')
    new_inner = new_top.top(points)
    new_scene = regional_top(candidate, points, opening_ceiling)
    depth = np.repeat(new_rim, 3) - new_inner
    valid = np.isfinite(new_inner) & np.isfinite(depth) & (depth > min_depth)
    valid &= np.isfinite(new_scene) & (np.abs(new_scene - new_inner) <= epsilon)
    fraction = float(valid[eligible].mean())
    details = [{'xy_m': points[i].tolist(), 'passed': bool(valid[i]),
                'candidate_depth_m': float(depth[i]) if np.isfinite(depth[i]) else None,
                'bottom_exposed': bool(np.isfinite(new_inner[i]) and np.isfinite(new_scene[i])
                                       and abs(new_inner[i] - new_scene[i]) <= epsilon)}
               for i in np.flatnonzero(eligible)]
    return {'status': 'measured', 'passed': fraction >= .9, 'score': fraction,
            'probes': details, 'minimum_nonzero_depth_m': min_depth, 'numerical_epsilon_m': epsilon,
            'opening_prism_margin_fraction': .05,
            'reference_hidden_depth_required': False, 'candidate_names_used_as_answers': False,
            'threshold_status': 'pilot_not_calibrated',
            'scope': 'Finite bottom/rim probes in the opening prism; not continuous walls, watertightness or support'}
