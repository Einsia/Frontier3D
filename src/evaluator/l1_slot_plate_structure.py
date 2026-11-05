"""Independent Code014 topology, whole-wall bands and used-material evidence.

Consumes inspector-owned scene facts and separately rooted initial evidence.
Not a replacement for complete target/protected surfaces or a score activation.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path

import numpy as np

from .l1_materials import SCOPES
from .l1_sleeve import unavailable, verdict
from .l1_slot_plate_baseline import initial_parameters
from .l1_slot_plate_sections import validate_design
from .l1_slot_plate_surface import measure_parameters
from .l1_slot_plate_topology import measure_plate_topology
from .l1_slot_plate_walls import measure_plate_walls
from .l1_surface import load_surface
from .l1_washer_edit import uniform_preservation


def inspect_plate_structure(scene, baseline, design, *, trusted_root, baseline_root,
                            material_scope, material_tolerance, deadline):
    validate_design(design)
    if (type(deadline) not in (int, float) or not np.isfinite(deadline)
            or material_scope not in SCOPES or type(material_tolerance) not in (int, float)
            or not np.isfinite(material_tolerance) or not 0 <= material_tolerance < 1e-3):
        raise ValueError('Explicit finite structure deadline and bounded material policy required')
    meshes, sources, objects = {}, {}, {}
    for label, facts, root in [('candidate', scene, trusted_root), ('initial', baseline, baseline_root)]:
        rows = [(name, row) for name, row in facts.get('objects', {}).items()
                if row.get('type') == 'MESH' and row.get('entity_scope') == 'delivery_geometry']
        if (len(rows) != 1 or any(r.get('entity_scope') == 'unsupported_delivery_geometry'
                                 for r in facts.get('objects', {}).values())):
            raise ValueError('Expected one actual editable plate in each trusted scene')
        name, row = rows[0]
        valid = (row.get('valid_solid') is True and row.get('closed') is True
                 and row.get('components') == 1 and row.get('editable') is True)
        meshes[label] = load_surface(row['mesh_payload'], Path(root))
        objects[label] = row
        sources[label] = {'object': name, 'trusted_solid': valid,
            'mesh_payload': copy.deepcopy(row['mesh_payload']),
            'material_surface': copy.deepcopy(row.get('material_surface'))}
    checks, parameters = measure_parameters(meshes['candidate'], design,
        solid_validated=sources['candidate']['trusted_solid'], deadline=deadline)
    topology = measure_plate_topology(meshes['candidate'], design,
        solid_validated=sources['candidate']['trusted_solid'], deadline=deadline)
    walls = measure_plate_walls(meshes['candidate'], design, parameters, topology, deadline=deadline)
    try:
        initial = initial_parameters(meshes['initial'], solid_validated=sources['initial']['trusted_solid'],
                                     deadline=deadline)
        initial_check = {'status': 'passed', 'passed': True, 'parameters': initial}
    except (ValueError, TimeoutError) as error:
        initial_check = unavailable(str(error))
    if initial_check['passed'] and time.monotonic() < deadline:
        material = uniform_preservation(objects['candidate'], objects['initial'],
            trusted_root=trusted_root, baseline_root=baseline_root,
            scope=material_scope, tolerance=material_tolerance)
        if time.monotonic() >= deadline:
            material = unavailable('Material result missed structure measurement deadline')
    else:
        material = unavailable('Public initial representation or material measurement budget unavailable')
    return {**verdict(target_parameters=checks, initial_parameters=initial_check,
        independent_passages=topology, whole_walls=walls, material_preservation=material),
        'protocol': 'l1-slot-plate-structure-inspection-v1', 'sources': sources,
        'design': copy.deepcopy(design), 'constrained_target_parameters': parameters,
        'full_task_verified': False, 'scoring_activated': False,
        'pending': ['Complete target and protected surfaces are separate mandatory checks',
                    'All-seed candidate execution, whole-task score integration and calibration',
                    'General procedural shader equivalence and nonplanar exterior representations'],
        'material_policy': {'scope': material_scope, 'parameter_tolerance': material_tolerance,
                            'calibration_status': 'pilot_pending_calibration'}}
