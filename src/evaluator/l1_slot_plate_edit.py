"""Case-specific Code014 numerical gates from complete trusted mesh evidence."""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np

from .l1_materials import SCOPES
from .l1_polyhedral_bounds import compare_polyhedral
from .l1_sleeve import unavailable, verdict
from .l1_slot_plate_preservation import compare_plate_preservation
from .l1_slot_plate_sections import validate_design
from .l1_slot_plate_structure import inspect_plate_structure
from .l1_slot_plate_surface import reference_surface
from .l1_surface import load_surface

PROTOCOL = 'l1-slot-plate-edit-v1'
FEATURES = {'solid', 'target_parameters', 'surface', 'independent_passages', 'whole_walls',
            'protected_surface', 'material_preservation'}


def nominal_target(design):
    """Task-owned allowed edit; candidate damage never enlarges this mask."""
    x, y, z = design['box_size_m']
    return {'box_bounds_m': [[-x/2, -y/2, 0.], [x/2, y/2, z]],
        'slots': [{'kind': 'slot', 'center_xy_m': [0., row],
                   'half_length_m': design['slot_half_centers_m'], 'radius_m': design['slot_radius_m']}
                  for row in design['slot_rows_y_m']],
        'bores': [{'lower': {'kind': 'circle', 'center_xy_m': center, 'radius_m': design['hole_radius_m']},
                   'upper': {'kind': 'circle', 'center_xy_m': center, 'radius_m': design['counterbore_radius_m']},
                   'shoulder_z_m': z-design['counterbore_depth_m']}
                  for center in design['hole_centers_xy_m']]}


def validate_policy(design, material_tolerance):
    validate_design(design)
    if (type(material_tolerance) not in (int, float) or not np.isfinite(material_tolerance)
            or not 0 <= material_tolerance < 1e-3):
        raise ValueError('Explicit bounded plate material tolerance required')


def inspect_slot_plate_edit(scene, baseline, design, *, trusted_root, material_scope,
                            material_tolerance, deadline, quality_mode=False):
    validate_policy(design, material_tolerance)
    if (type(deadline) not in (int, float) or not np.isfinite(deadline) or material_scope not in SCOPES):
        raise ValueError('Finite plate edit deadline and supported material scope required')
    root = Path(trusted_root)
    report = {'protocol': PROTOCOL, 'design': copy.deepcopy(design), 'material_scope': material_scope,
        'material_tolerance': material_tolerance, 'full_task_verified': False,
        'scope': 'Complete supported plate geometry and constant-used-material gates; not all EVALUATION clauses',
        'calibration_status': 'pilot_pending_calibration'}
    candidates = [r for r in scene.get('objects', {}).values()
                  if r.get('type') == 'MESH' and r.get('entity_scope') == 'delivery_geometry']
    if len(candidates) == 1 and not {'valid_solid', 'closed', 'editable', 'components'} <= candidates[0].keys():
        raise ValueError('Candidate solid inspection evidence is incomplete')
    solid = (len(candidates) == 1 and candidates[0].get('valid_solid') is True
        and candidates[0].get('closed') is True and candidates[0].get('editable') is True
        and candidates[0].get('components') == 1
        and not any(r.get('entity_scope') == 'unsupported_delivery_geometry' for r in scene.get('objects', {}).values()))
    features = {name: unavailable('Candidate is not one trusted editable closed solid') for name in sorted(FEATURES)}
    features['solid'] = {'status': 'passed' if solid else 'failed', 'passed': solid}
    if not solid:
        return {**report, **{k: v for k, v in verdict(**features).items() if k != 'measurements'}, 'features': features}
    started = time.monotonic()
    structure = inspect_plate_structure(scene, baseline, design, trusted_root=root, baseline_root=root,
        material_scope=material_scope, material_tolerance=material_tolerance,
        deadline=min(deadline, started+min(30., max(0., deadline-started)/3)))
    features.update({k: structure['measurements'][k] for k in
        ('target_parameters', 'independent_passages', 'whole_walls', 'material_preservation')})
    target = structure['constrained_target_parameters']
    target_source = 'independently_fitted_candidate'
    if quality_mode and target is None:
        target = nominal_target(design)
        target_source = 'frozen_task_nominal_design'
        passages = features['independent_passages']
        if features['whole_walls']['status'] == 'not_measurable' and passages['status'] == 'failed':
            features['whole_walls'] = {'status': 'failed', 'passed': False,
                'reason': 'Required complete passage walls cannot pass when passage topology is measured absent or invalid',
                'dependency': 'independent_passages', 'dimension_fit_available': False}
    initial_check = structure['measurements']['initial_parameters']
    for key in ('surface', 'protected_surface'):
        features[key] = unavailable('Independent target/initial parameters or budget unavailable')
    approximation = None
    if target is not None and initial_check['passed'] and time.monotonic() < deadline:
        candidate = load_surface(structure['sources']['candidate']['mesh_payload'], root)
        original = load_surface(structure['sources']['initial']['mesh_payload'], root)
        now = time.monotonic()
        try:
            reference, approximation = reference_surface(target, error_m=design['dimension_tolerance_m']/16)
            features['surface'] = compare_polyhedral(candidate, reference,
                tolerance_m=design['dimension_tolerance_m'],
                approximation_m=approximation['continuous_hausdorff_bound_m'],
                deadline=now+max(0., deadline-now)/2)
        except (ValueError, TimeoutError) as error:
            features['surface'] = unavailable(str(error))
        features['protected_surface'] = compare_plate_preservation(candidate, original,
            initial_check['parameters'], target, tolerance_m=design['preservation_tolerance_m'], deadline=deadline)
    return {**report, **{k: v for k, v in verdict(**features).items() if k != 'measurements'},
        'features': features, 'sources': structure['sources'], 'initial_parameters': initial_check,
        'constrained_target_parameters': structure['constrained_target_parameters'],
        'comparison_target_parameters': target, 'comparison_target_source': target_source,
        'reference_approximation': approximation}
