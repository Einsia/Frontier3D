"""Layered analytic initial/target HOLE symmetric difference for Code014.

The target's low-dimensional hole parameters must first pass independent
public dimensions; extra candidate damage never expands this region. Exterior
box displacement is deliberately NOT in the allowed-difference calculation.
Circle/capsule inner/outer polygons bound the analytic difference. This kernel
does not authenticate the caller or certify task-specific mask calibration.
"""
from __future__ import annotations

from itertools import pairwise

import numpy as np
import shapely

from .l1_prism_mask import GUARD

SEGMENTS = 128
# Explicit allowed-region representation neighbourhood, not a distance-gate
# relaxation. At this resolution the largest public 4.5 mm circle has <85 nm
# chord error. 256 nm also covers the 8 nm arithmetic guard and closed caps.
# This pilot policy needs calibration/review before whole-task activation.
BOUNDARY_NEIGHBOURHOOD_M = 256e-9


def profile_enclosures(profile, radius=None):
    center = np.asarray(profile['center_xy_m'], dtype=float)
    radius = profile['radius_m'] if radius is None else radius
    if (center.shape != (2,) or not np.isfinite(center).all() or type(radius) not in (int, float)
            or not np.isfinite(radius) or radius <= 64*GUARD):
        raise ValueError('Invalid analytic feature profile')
    if profile['kind'] == 'circle':
        axis = shapely.Point(center)
    elif profile['kind'] == 'slot':
        half = profile['half_length_m']
        if type(half) not in (int, float) or not np.isfinite(half) or half <= 64*GUARD:
            raise ValueError('Invalid analytic capsule length')
        axis = shapely.LineString([center+[-half, 0.], center+[half, 0.]])
    else:
        raise ValueError('Unsupported analytic feature profile')
    # Inner chords lie inside the true tube. Outer polygon's edge apothem
    # exceeds the true radius; the same construction also encloses capsules.
    return (axis.buffer(radius-GUARD, quad_segs=SEGMENTS),
            axis.buffer((radius+GUARD)/np.cos(np.pi/(4*SEGMENTS)), quad_segs=SEGMENTS))


def radial_enclosures(profile):
    lower, upper = profile.get('boundary_radius_interval_m', [profile['radius_m']]*2)
    if (any(type(v) not in (float, int) or not np.isfinite(v) for v in (lower, upper))
            or not 64*GUARD < lower <= profile['radius_m'] <= upper
            or upper-lower > .00015):
        raise ValueError('Invalid independently measured profile representation interval')
    return profile_enclosures(profile, lower), profile_enclosures(profile, upper)


def allowed_difference(initial, target):
    """Finite prism union: exact-layer analytic XOR, safely enclosed in XY/Z."""
    bounds = np.asarray(initial['box_bounds_m'], dtype=float)
    other = np.asarray(target['box_bounds_m'], dtype=float)
    if (bounds.shape != (2, 3) or other.shape != (2, 3) or not np.isfinite([bounds, other]).all()
            or np.any(bounds[1]-bounds[0] <= 64*GUARD) or np.any(other[1]-other[0] <= 64*GUARD)
            or len(initial['slots']) != 2 or len(target['slots']) != 2 or len(target['bores']) != 2):
        raise ValueError('Invalid initial/target layer design')
    box = shapely.box(bounds[0, 0], bounds[0, 1], bounds[1, 0], bounds[1, 1])
    old = [radial_enclosures(p) for p in initial['slots']]
    slots = [radial_enclosures(p) for p in target['slots']]
    bores = [(radial_enclosures(b['lower']), radial_enclosures(b['upper']), b['shoulder_z_m'])
             for b in target['bores']]
    lo, hi = min(bounds[0, 2], other[0, 2]), max(bounds[1, 2], other[1, 2])
    if any(type(z) not in (int, float) or not np.isfinite(z) or not lo < z < hi for _, _, z in bores):
        raise ValueError('Invalid shoulder layer')
    domains = slots+[high for _, high, _ in bores]
    if (any(not box.contains(p[1][1]) for p in domains+old)
            or any(domains[i][1][1].intersects(domains[j][1][1]) for i in range(4) for j in range(i))):
        raise ValueError('Allowed features intersect each other or protected exterior box')
    old_bounds = [[shapely.union_all([p[radial][enclosure] for p in old]) for enclosure in (0, 1)]
                  for radial in (0, 1)]
    heights = sorted({float(lo), float(hi), *(float(z) for _, _, z in bores)})
    regions = []
    for lower, upper in pairwise(heights):
        middle = (lower+upper)/2
        chosen = slots+[high if middle > z else low for low, high, z in bores]
        new_bounds = [[shapely.union_all([p[radial][enclosure] for p in chosen]) for enclosure in (0, 1)]
                      for radial in (0, 1)]
        # Union of possible XORs for the independently measured radial bands:
        # (old_max - new_min) U (new_max - old_min). This handles valid circular
        # chords on BOTH the authoritative initial and rebuilt target meshes.
        # It is not the union of whole holes: common void cores remain outside.
        inner = old_bounds[1][0].difference(new_bounds[0][1]).union(
            new_bounds[1][0].difference(old_bounds[0][1]))
        outer = old_bounds[1][1].difference(new_bounds[0][0]).union(
            new_bounds[1][1].difference(old_bounds[0][0]))
        # The declared allowed set is the CLOSED analytic XOR plus a product
        # neighbourhood (XY disk, Z interval), not the raw open subtraction.
        # Inscribed/circumscribed buffers respectively enclose that SAME set.
        # This gives legal closed hole walls/caps representation space without
        # excluding arbitrary exterior-box displacement or candidate defects.
        pad = BOUNDARY_NEIGHBOURHOOD_M
        inner = inner.buffer(pad-GUARD, quad_segs=SEGMENTS)
        outer = outer.buffer((pad+GUARD)/np.cos(np.pi/(4*SEGMENTS)), quad_segs=SEGMENTS)
        if not inner.is_valid or not outer.is_valid or not outer.covers(inner):
            raise ValueError('Invalid initial/target difference enclosure')
        regions.append({'inner': inner, 'outer': outer,
            'inner_span_m': [lower-pad+GUARD, upper+pad-GUARD],
            'outer_span_m': [lower-pad-GUARD, upper+pad+GUARD],
            'layer_span_m': [lower, upper]})
    return regions


def mask_summary(regions):
    return {'protocol': 'l1-slot-plate-allowed-hole-difference-v1', 'numeric_guard_m': GUARD,
        'boundary_neighbourhood_xy_m': BOUNDARY_NEIGHBOURHOOD_M,
        'boundary_neighbourhood_z_m': BOUNDARY_NEIGHBOURHOOD_M,
        'boundary_policy_status': 'Explicit representation neighbourhood; pilot calibration pending',
        'circle_quad_segments': SEGMENTS, 'exterior_box_change_allowed': False,
        'policy': 'Union of closed initial/target XORs within independently measured radial representation bands, plus declared XY/Z neighbourhood',
        'layers': [{'span_m': r['layer_span_m'], 'inner_xy_area_m2': r['inner'].area,
                    'outer_xy_area_m2': r['outer'].area} for r in regions]}
