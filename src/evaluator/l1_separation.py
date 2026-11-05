"""World-solid clearance evidence, independent of explosion direction or names.

Closest features of two triangles are vertex/face, edge/edge, or intersecting
faces. Enumerate all potentially closer triangle pairs with conservative sphere
and box pruning. This is floating-point mesh evidence, not an exact-arithmetic
certificate or a task-specific explosion/legibility verdict.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np

from .l1_mesh import triangle_intersection
from .l1_surface import (
    SurfaceMesh,
    _distances_to_triangles,
    load_surface,
    surface_distances,
)
from .l1_triangle_batch import triangle_distances
from .l1_volume_math import winding_classification

PROTOCOL = 'l1-solid-clearance-v1'
MAX_TRIANGLE_PAIRS = 200000


def triangle_distance(left, right):
    """Minimum of complete triangle features, including interior edge crossings."""
    if triangle_intersection(left, right, 0.0):
        return 0.0
    best = min(*(float(_distances_to_triangles(p, right[None])[0]) for p in left),
               *(float(_distances_to_triangles(p, left[None])[0]) for p in right))
    p = np.repeat(left, 3, axis=0)
    q = np.tile(right, (3, 1))
    u = np.repeat(np.roll(left, -1, axis=0) - left, 3, axis=0)
    v = np.tile(np.roll(right, -1, axis=0) - right, (3, 1))
    normal = np.cross(u, v)
    denominator = np.sum(normal * normal, axis=1)
    nonparallel = denominator > 0
    if np.any(nonparallel):
        p, q, u, v, normal, denominator = [a[nonparallel] for a in (p, q, u, v, normal, denominator)]
        s = np.sum(np.cross(q - p, v) * normal, axis=1) / denominator
        t = np.sum(np.cross(q - p, u) * normal, axis=1) / denominator
        valid = (s >= 0) & (s <= 1) & (t >= 0) & (t <= 1)
        if np.any(valid):
            distances = np.linalg.norm(p + s[:, None] * u - q - t[:, None] * v, axis=1)
            best = min(best, float(distances[valid].min()))
    # Endpoint/segment minima are already included in vertex/face distances.
    return best


def surface_clearance(left: SurfaceMesh, right: SurfaceMesh, *, guard_m: float, max_pairs: int) -> dict:
    # Surface witnesses give an upper bound; disjoint world boxes only a lower
    # bound. Equality within the existing numerical guard resolves the minimum
    # without enumerating every coplanar triangle pair of parallel flange faces.
    # Overlapping boxes alone never prove contact, containment or separation.
    witness_indices = np.unique(np.r_[0, left.vertices.argmin(axis=0), left.vertices.argmax(axis=0)])
    upper = float(surface_distances(left.vertices[witness_indices], right).min())
    left_low, left_high = left.vertices.min(axis=0), left.vertices.max(axis=0)
    right_bounds_low, right_bounds_high = right.vertices.min(axis=0), right.vertices.max(axis=0)
    gap = np.maximum(np.maximum(right_bounds_low-left_high, left_low-right_bounds_high), 0)
    global_lower = float(np.linalg.norm(gap))

    def bounded_minimum(count, closest):
        return {'status': 'ok', 'distance_m': upper, 'closest_triangles': closest,
                'candidate_pairs_evaluated': count, 'minimum_resolved': True,
                'minimum_interval_m': [min(global_lower, upper), upper],
                'method': 'world_box_lower_bound_and_actual_surface_witness'}

    if upper-global_lower <= guard_m:
        return bounded_minimum(0, None)
    closest = None
    count = 0
    right_low, right_high = right.xyz.min(axis=1), right.xyz.max(axis=1)
    max_radius = float(right.radii.max())
    for index, triangle in enumerate(left.xyz):
        candidates = np.asarray(right.tree.query_ball_point(
            left.centers[index], left.radii[index] + max_radius + upper + guard_m), dtype=int)
        if not len(candidates):
            continue
        sphere_lower = np.linalg.norm(right.centers[candidates] - left.centers[index], axis=1) - right.radii[candidates] - left.radii[index]
        gaps = np.maximum(np.maximum(right_low[candidates] - triangle.max(axis=0), triangle.min(axis=0) - right_high[candidates]), 0)
        lower = np.maximum(sphere_lower, np.linalg.norm(gaps, axis=1))
        ordered = np.argsort(lower, kind='stable')
        position = 0
        while position < len(ordered):
            if lower[ordered[position]] > upper + guard_m:
                break
            if count >= max_pairs:
                return {'status': 'not_measurable', 'reason': 'Triangle-pair budget exceeded',
                        'candidate_pairs_evaluated': count, 'upper_bound_m': upper}
            # Vectorize complete triangle features, not surface samples. Each
            # evaluated pair still consumes the original hard pair budget.
            ranks = ordered[position:position+min(64,max_pairs-count)]
            ranks = ranks[lower[ranks] <= upper+guard_m]
            position += len(ranks)
            selected = candidates[ranks]
            values = triangle_distances(triangle,right.xyz[selected])
            count += len(selected)
            winner = int(np.argmin(values))
            other,value = int(selected[winner]),float(values[winner])
            if value <= upper:
                upper, closest = value, [index, other]
            if upper-global_lower <= guard_m:
                return bounded_minimum(count, closest)
            if upper <= guard_m:
                return {'status': 'ok', 'distance_m': upper, 'closest_triangles': closest,
                        'candidate_pairs_evaluated': count, 'minimum_resolved': False}
    return {'status': 'ok', 'distance_m': upper, 'closest_triangles': closest,
            'candidate_pairs_evaluated': count, 'minimum_resolved': True}


def compare_solid_clearance(left_record: dict, right_record: dict, *, trusted_root: Path,
                            max_pairs: int = MAX_TRIANGLE_PAIRS) -> dict:
    report = {'protocol': PROTOCOL, 'status': 'not_measurable', 'hard_gate': False,
              'coordinate_space': 'world_metres', 'alignment': 'none', 'inputs': {},
              'relation': 'unknown', 'solid_disjoint': None, 'clearance_m': None,
              'limitations': ['Floating-point triangulated geometry, not exact arithmetic',
                              'Numerical guard is not a task clearance threshold',
                              'No task role, separation direction, material or legibility verdict']}
    try:
        if type(max_pairs) is not int or not 1 <= max_pairs <= MAX_TRIANGLE_PAIRS:
            raise ValueError('Invalid triangle-pair budget')
        if any(record.get('volume_reliable') is not True for record in (left_record, right_record)):
            raise ValueError('Two validated connected closed solids are required')
        for side, record in (('left', left_record), ('right', right_record)):
            report['inputs'][side] = {key: record['mesh_payload'][key] for key in ('path', 'sha256', 'coordinate_space')}
        left, right = [load_surface(record['mesh_payload'], trusted_root) for record in (left_record, right_record)]
        coordinate_scale = max(1., float(np.abs(left.vertices).max()), float(np.abs(right.vertices).max()))
        guard = max(1e-9, 128 * np.finfo(float).eps * coordinate_scale)
        report['numerical_guard_m'] = guard
        # Common translation improves arithmetic; no relative alignment or scale.
        origin = left.vertices[0]
        left, right = [SurfaceMesh(mesh.vertices - origin, mesh.triangles) for mesh in (left, right)]
        measured = surface_clearance(left, right, guard_m=guard, max_pairs=max_pairs)
        report['surface'] = measured
        if measured['status'] != 'ok':
            report['reason'] = measured['reason']
            return report
        distance = measured['distance_m']
        if distance <= guard:
            report.update(status='ok', relation='boundary_contact_intersection_or_guard_band',
                          solid_disjoint=None, clearance_m=None)
            return report
        # For validated connected closed surfaces with positive separation, a
        # representative on each surface detects either containment direction.
        # A shaft inside a through-hole remains outside the surrounding solid.
        inside = [int(winding_classification(target.vertices, target.triangles, source.vertices[:1],
                                             epsilon_m=guard)[0]) for source, target in ((left, right), (right, left))]
        report['containment_probes'] = {'left_in_right': inside[0], 'right_in_left': inside[1]}
        if -1 in inside:
            report['reason'] = 'Ambiguous solid containment'
        elif 1 in inside:
            report.update(status='ok', relation='solid_containment', solid_disjoint=False, clearance_m=0.)
        else:
            report.update(status='ok', relation='positive_clearance', solid_disjoint=True, clearance_m=distance)
    except (KeyError, TypeError, ValueError, OSError, FloatingPointError) as error:
        report.update(status='not_measurable', reason=str(error))
    return report


def compare_state_separation(first: dict, middle: dict, *, trusted_root: Path) -> dict:
    """Identity maps are validated by the single-session return entry point."""
    report = {'protocol': 'l1-state-separation-v1', 'status': 'not_measurable', 'hard_gate': False,
              'scope': 'first_and_middle_world_solid_clearance_by_fixed_identity',
              'task_verdict': 'not_configured', 'pairs': [], 'all_middle_pairs_disjoint': None,
              'not_assessed': ['task_required_separation_relations', 'task_gap_thresholds',
                               'explosion_legibility', 'full_cycle_materials']}
    if set(first) != set(middle) or not 2 <= len(first) <= 64:
        report['reason'] = 'Matching identity sets with 2 to 64 parts required'
        return report
    for left, right in itertools.combinations(sorted(first), 2):
        row = {'identities': [left, right]}
        for name, state in (('first', first), ('middle', middle)):
            row[name] = compare_solid_clearance(state[left][1], state[right][1], trusted_root=trusted_root)
        before, after = row['first'], row['middle']
        row['clearance_change_m'] = (after['clearance_m'] - before['clearance_m']
                                     if all(r['clearance_m'] is not None for r in (before, after)) else None)
        report['pairs'].append(row)
    rows = report['pairs']
    report['status'] = 'ok' if all(r[s]['status'] == 'ok' for r in rows for s in ('first', 'middle')) else 'not_measurable'
    middle_states = [row['middle']['solid_disjoint'] for row in rows]
    report['all_middle_pairs_disjoint'] = (False if False in middle_states else
                                          True if all(s is True for s in middle_states) else None)
    return report
