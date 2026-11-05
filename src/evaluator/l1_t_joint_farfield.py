"""Partial Code013 preservation: complete actual surfaces in two fixed Z slabs.

The slabs are a subset of the protected domain, independent of the candidate.
They contain both main ends and far cylindrical walls; the junction slab is
NOT granted permission to change. Full junction protection remains pending.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np

from .l1_clipped_plane_cover import clipped_plane_cover
from .l1_polyhedral_bounds import directed_polyhedral
from .l1_protected_surface import near_planar_cover, split_polygon, triangulate
from .l1_revolution import EPSILON_M, convex_patch_neighbors, triangle_to_mesh_upper
from .l1_sleeve import unavailable, verdict
from .l1_surface import load_surface
from .l1_t_joint_paths import validate_design

GUARD_M = 8e-9


def protected_slabs(design):
    validate_design(design)
    # A legal center-Z error <=t plus a legal diameter error <=t contributes
    # at most t+t/2 to the branch's Z extent. Neither is a measured defect.
    extent = design['branch_outer_radius_m']+1.5*design['dimension_tolerance_m']+2*GUARD_M
    z = design['branch_z_m']
    return {'lower': z-extent, 'upper': z+extent,
            'basis': 'Fixed public center/radius plus independent legal position and diameter bounds',
            'junction_slab_is_allowed_mask': False}


def _clipped(mesh, limit, *, lower, deadline, max_patches):
    normal = np.array([0., 0., 1. if lower else -1.])
    offset = (limit if lower else -limit)+GUARD_M
    pieces = []
    for start in range(0, len(mesh.xyz), 64):
        if time.monotonic() >= deadline:
            raise TimeoutError('Protected-slab clipping deadline exhausted')
        for triangle in mesh.xyz[start:start+64]:
            values = triangle @ normal-offset
            if values.min() > 0:
                continue
            if values.max() <= 0:
                pieces.append(triangle)
            elif values.min() <= 0:
                polygon, _ = split_polygon(triangle, normal, offset)
                if len(polygon) >= 3:
                    pieces.extend(triangulate(polygon))
                elif len(polygon):
                    # Retain tangent point/edge traces, not just positive area.
                    pieces.append(np.resize(polygon, (3, 3)))
            if len(pieces) > max_patches:
                raise TimeoutError('Protected-slab clipping patch budget exhausted')
    return np.asarray(pieces).reshape(-1, 3, 3)


def _directed(fragments, target, tolerance, *, deadline, max_patches, max_depth, cache):
    if time.monotonic() >= deadline:
        raise TimeoutError('Protected-surface deadline exhausted')
    if 'pairs' not in cache:
        cache['pairs'] = convex_patch_neighbors(target)
    upper = triangle_to_mesh_upper(fragments, target, cache['pairs'])+GUARD_M
    covers = 0
    for index in np.flatnonzero(upper >= tolerance-EPSILON_M):
        if time.monotonic() >= deadline:
            raise TimeoutError('Protected-surface plane-cover deadline exhausted')
        covered, _ = near_planar_cover(fragments[index], target, tolerance-GUARD_M,
                                       cache=cache.setdefault('near', {}))
        if covered:
            upper[index] = (tolerance-GUARD_M-32*EPSILON_M)*np.sqrt(2)/3+EPSILON_M+GUARD_M
            covers += 1
            continue
        bound = clipped_plane_cover(fragments[index], target, tolerance-GUARD_M,
                                    deadline=deadline, cache=cache.setdefault('clipped', {}))
        if bound is not None:
            upper[index] = min(upper[index], bound+GUARD_M)
            covers += 1
    if time.monotonic() >= deadline:
        raise TimeoutError('Protected-surface cover result missed deadline')
    accepted = upper < tolerance-EPSILON_M
    proved = float(upper[accepted].max()) if accepted.any() else 0.
    summary = {'source_triangles': len(fragments), 'target_triangles': len(target.xyz),
               'clipped_plane_proofs': covers, 'processed_patches': len(fragments),
               'tolerance_m': tolerance, 'approximation_m': GUARD_M}
    if accepted.all():
        return {**summary, 'status': 'passed', 'passed': True,
                'continuous_upper_bound_m': proved, 'witness_lower_bound_m': 0.}
    if max_patches <= len(fragments):
        return {**summary, **unavailable('Protected-surface patch budget exhausted'),
                'continuous_upper_bound_m': None, 'witness_lower_bound_m': 0.}
    result = directed_polyhedral(fragments[~accepted], target, tolerance_m=tolerance,
        approximation_m=GUARD_M, deadline=deadline, max_patches=max_patches-len(fragments), max_depth=max_depth)
    return {**result, **summary, 'processed_patches': len(fragments)+result['processed_patches'],
            'continuous_upper_bound_m': max(proved, result['continuous_upper_bound_m'])
                if result['passed'] else None}


def compare_t_joint_farfield(candidate, baseline, design, *, candidate_solid_validated,
                            baseline_solid_validated, deadline, max_triangles=262144,
                            max_patches=262144, max_depth=24):
    slabs = protected_slabs(design)
    if (type(candidate_solid_validated) is not bool or type(baseline_solid_validated) is not bool
            or type(deadline) not in (float, int) or not np.isfinite(deadline)
            or any(type(v) is not int or v <= 0 for v in (max_triangles, max_patches))
            or type(max_depth) is not int or not 0 <= max_depth <= 30):
        raise ValueError('Invalid trusted-solid evidence or protected-surface budget')
    report = {'protocol': 'l1-t-joint-farfield-v1', 'design': copy.deepcopy(design),
              'slabs_m': slabs, 'full_task_verified': False, 'formal_score_eligible': False,
              'full_protected_domain_verified': False,
              'scope': 'Actual main-tube ends and far walls only; junction-region protection not measured',
              'baseline_authority': 'actual_initial_world_mesh',
              'tolerance_m': design['preservation_tolerance_m'],
              'clipping_guard_m': GUARD_M,
              'limitations': ['Float64 guarded bounds, not exact arithmetic.',
                              'No target shape, full-wall dimensions, materials or complete solid validation.']}
    if not baseline_solid_validated:
        return {**report, 'status': 'infrastructure_error', 'passed': False,
                'reason': 'Authoritative initial solid evidence unavailable'}
    if not candidate_solid_validated:
        return {**report, **unavailable('Trusted candidate solid evidence unavailable')}
    if (time.monotonic() >= deadline or len(candidate.triangles) > max_triangles
            or len(baseline.triangles) > max_triangles):
        return {**report, **unavailable('Protected-surface input budget exhausted')}
    checks, caches = {}, {'initial_to_candidate': {}, 'candidate_to_initial': {}}
    # Keep two physical regions and both directions independently inspectable.
    for name, limit in [('lower', slabs['lower']), ('upper', slabs['upper'])]:
        for direction, source, target in [('initial_to_candidate', baseline, candidate),
                                          ('candidate_to_initial', candidate, baseline)]:
            key = name+'_'+direction
            try:
                fragments = _clipped(source, limit, lower=name == 'lower', deadline=deadline,
                                     max_patches=max_patches)
                if not len(fragments):
                    checks[key] = unavailable('No actual source surface in protected slab')
                    continue
                checks[key] = _directed(fragments, target, design['preservation_tolerance_m'],
                    deadline=deadline, max_patches=max_patches, max_depth=max_depth, cache=caches[direction])
            except TimeoutError as error:
                checks[key] = unavailable(str(error))
    if time.monotonic() >= deadline:
        return {**report, **unavailable('Protected-surface result missed deadline'), 'measurements': checks}
    return {**report, **verdict(**checks)}


def _trusted_mesh(scene, root):
    objects = scene.get('objects', {})
    rows = [(name, row) for name, row in objects.items()
            if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
    if len(rows) != 1 or any(row.get('entity_scope') == 'unsupported_delivery_geometry' for row in objects.values()):
        raise ValueError('One trusted editable delivery mesh required')
    name, row = rows[0]
    if not {'valid_solid', 'closed', 'components', 'editable', 'mesh_payload'} <= row.keys():
        raise ValueError('Missing trusted solid evidence')
    valid = (row['valid_solid'] is True and row['closed'] is True and row['editable'] is True
             and type(row['components']) is int and row['components'] == 1)
    mesh = load_surface(row['mesh_payload'], Path(root))
    return mesh, valid, {'object': name, 'mesh_payload': copy.deepcopy(row['mesh_payload']), 'trusted_solid': valid}


def inspect_t_joint_farfield(scene, baseline, design, *, trusted_root, baseline_root, deadline, **budget):
    """Separate evaluator-owned roots and hashes for candidate and initial."""
    validate_design(design)
    candidate_mesh, candidate_valid, candidate_source = _trusted_mesh(scene, trusted_root)
    baseline_mesh, baseline_valid, baseline_source = _trusted_mesh(baseline, baseline_root)
    result = compare_t_joint_farfield(candidate_mesh, baseline_mesh, design,
        candidate_solid_validated=candidate_valid, baseline_solid_validated=baseline_valid,
        deadline=deadline, **budget)
    return {**result, 'sources': {'candidate': candidate_source, 'initial': baseline_source}}
