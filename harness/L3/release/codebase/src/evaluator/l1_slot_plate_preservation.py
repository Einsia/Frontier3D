"""Code014 continuous world-surface protection outside enclosed hole edits."""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np

from .l1_polyhedral_bounds import directed_polyhedral
from .l1_prism_mask import CLIP_ERROR_M, clip_protected
from .l1_revolution import EPSILON_M
from .l1_sleeve import unavailable, verdict
from .l1_slot_plate_baseline import initial_parameters
from .l1_slot_plate_mask import allowed_difference, mask_summary
from .l1_slot_plate_surface import measure_parameters
from .l1_surface import load_surface


def directed_preservation(source, target, regions, *, tolerance_m, deadline, max_patches=262144):
    started = time.monotonic()
    possible, clipping = clip_protected(source, regions, envelope='inner',
        deadline=started+max(0., deadline-started)/3, max_triangles=max_patches)
    if possible is None:
        return {'status': 'not_measurable', 'passed': False, 'possible_protection_clipping': clipping}
    if not len(possible):
        return {'status': 'passed', 'passed': True, 'possible_protection_clipping': clipping,
                'reason': 'All source surface is certified inside allowed region'}
    now = time.monotonic()
    broad = directed_polyhedral(possible, target, tolerance_m=tolerance_m,
        approximation_m=CLIP_ERROR_M,
        deadline=now+max(0., deadline-now)*.7, max_patches=max_patches)
    result = {'possible_protection_clipping': clipping, 'possible_protection_bound': broad}
    if broad['status'] == 'passed':
        return {**result, 'status': 'passed', 'passed': True}
    # A discrepancy in the conservative boundary belt may be a legal edit.
    # Only actual points OUTSIDE the outer allowed enclosure can reject.
    certain, clipping = clip_protected(source, regions, envelope='outer', deadline=deadline, max_triangles=max_patches)
    result['certain_protection_clipping'] = clipping
    if certain is not None and len(certain):
        narrow = directed_polyhedral(certain, target, tolerance_m=tolerance_m,
            approximation_m=CLIP_ERROR_M, deadline=deadline, max_patches=max_patches)
        result['certain_protection_bound'] = narrow
        if narrow['status'] == 'failed':
            return {**result, 'status': 'failed', 'passed': False,
                    'reason': 'Actual source point is outside allowed outer enclosure and exceeds preservation tolerance'}
    return {**result, 'status': 'not_measurable', 'passed': False,
            'reason': 'Possible protected region unresolved; no certain protected failure witness'}


def compare_plate_preservation(candidate, baseline, initial, constrained_target, *, tolerance_m,
                               deadline, max_patches=262144):
    if (any(type(v) not in (int, float) or not np.isfinite(v) for v in (tolerance_m, deadline))
            or tolerance_m-CLIP_ERROR_M <= 64*EPSILON_M or type(max_patches) is not int or max_patches <= 0):
        raise ValueError('Invalid preservation tolerance or clipping/measurement budget')
    regions = allowed_difference(initial, constrained_target)
    now = time.monotonic()
    forward = directed_preservation(candidate, baseline, regions, tolerance_m=tolerance_m,
        deadline=now+max(0., deadline-now)/2, max_patches=max_patches)
    reverse = directed_preservation(baseline, candidate, regions, tolerance_m=tolerance_m,
        deadline=deadline, max_patches=max_patches)
    statuses = {forward['status'], reverse['status']}
    status = 'failed' if 'failed' in statuses else 'passed' if statuses == {'passed'} else 'not_measurable'
    return {'protocol': 'l1-slot-plate-protected-surface-v1', 'status': status, 'passed': status == 'passed',
        'tolerance_m': tolerance_m, 'alignment': 'None; public initial world coordinates retained',
        'allowed_region': mask_summary(regions), 'candidate_to_initial': forward, 'initial_to_candidate': reverse,
        'full_task_verified': False, 'scope': 'Protected surface distance only, not target/occupancy/material correctness'}


def inspect_plate_preservation(scene, baseline, design, *, trusted_root, baseline_root, deadline):
    """Trusted facts only; recompute constrained target/initial bands internally."""
    if type(deadline) not in (int, float) or not np.isfinite(deadline):
        raise ValueError('Finite protected-surface measurement deadline required')
    meshes, sources = {}, {}
    for label, facts, root in [('candidate', scene, trusted_root), ('initial', baseline, baseline_root)]:
        rows = [(name, row) for name, row in facts.get('objects', {}).items()
                if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
        if (len(rows) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry'
                                 for r in facts.get('objects', {}).values())):
            raise ValueError('Expected one editable actual plate in each trusted scene')
        name, row = rows[0]
        valid = (row.get('valid_solid') is True and row.get('closed') is True
                 and row.get('components') == 1 and row.get('editable') is True)
        meshes[label] = load_surface(row['mesh_payload'], Path(root))
        sources[label] = {'object': name, 'trusted_solid': valid,
                          'mesh_payload': copy.deepcopy(row['mesh_payload'])}
    parameters_check, target = measure_parameters(meshes['candidate'], design,
        solid_validated=sources['candidate']['trusted_solid'], deadline=deadline)
    initial = None
    try:
        initial = initial_parameters(meshes['initial'], solid_validated=sources['initial']['trusted_solid'], deadline=deadline)
        initial_check = {'status': 'passed', 'passed': True, 'parameters': initial}
    except (ValueError, TimeoutError) as error:
        initial_check = unavailable(str(error))
    if target is None or initial is None:
        protection = unavailable('Independent target dimensions and public initial representation required before masking')
    else:
        protection = compare_plate_preservation(meshes['candidate'], meshes['initial'], initial, target,
            tolerance_m=design['preservation_tolerance_m'], deadline=deadline)
    return {**verdict(target_parameters=parameters_check, initial_parameters=initial_check, protected_surface=protection),
        'protocol': 'l1-slot-plate-protection-inspection-v1', 'sources': sources,
        'constrained_target_parameters': target, 'initial_parameters': initial,
        'full_task_verified': False, 'scoring_activated': False,
        'pending': ['Full target surface and all-height dimensions remain separate gates',
                    'Material preservation, globally independent passages, seed integration and mask calibration']}
