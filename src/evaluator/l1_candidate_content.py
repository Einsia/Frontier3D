"""Zero only the check contradicted by completed, trusted candidate evidence."""
from __future__ import annotations

import math

POLICY = 'candidate-content-partial-zero-v1'


def absent_feature_body(check, evidence, spec):
    """Prove that no delivered mesh has the check's required dimensions.

    A missing collector, partial inspection, unsupported geometry, ambiguous
    selection or malformed facts is not evidence of incorrect candidate content.
    The original hole probe must have explicitly reported an unavailable body.
    """
    if spec.profile != 'L1' or 'l1_protocol' not in spec.to_dict():
        return None
    probes = evidence.get('probes', {})
    if check.id not in probes or probes[check.id] is not None:
        return None
    inspection = evidence.get('inspector_execution', {})
    if inspection.get('status') != 'completed':
        return None
    if evidence.get('measurement_failures', {}).get(check.id):
        return None
    params = check.params
    if 'objects' in params:  # Names alone do not establish a semantic defect.
        return None
    expected = params.get('object_dimensions')
    if not isinstance(expected, list) or len(expected) != 3:
        return None
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    if not all(finite(value) and value > 0 for value in expected):
        return None
    tolerance = params.get('object_dimension_tolerance', 1e-6)
    if isinstance(tolerance, str):
        tolerance = spec.to_dict().get('tolerances', {}).get(tolerance)
    if not finite(tolerance) or tolerance < 0:
        return None
    scene = evidence.get('scene', {})
    if (scene.get('coordinate_units') != 'metres'
            or not finite(scene.get('unit_scale')) or scene['unit_scale'] <= 0
            or scene.get('unsupported_geometry') != []
            or scene.get('has_instances') is not False):
        return None
    objects = scene.get('objects')
    if not isinstance(objects, dict) or scene.get('object_count') != len(objects):
        return None
    if any(not isinstance(row, dict) for row in objects.values()):
        return None
    meshes = {name: row for name, row in objects.items() if row.get('type') == 'MESH'}
    if scene.get('mesh_count') != len(meshes):
        return None
    considered = []
    for name, row in meshes.items():
        if row.get('visible_render') is False:
            continue
        dimensions = row.get('dimensions')
        if (not isinstance(dimensions, list) or len(dimensions) != 3
                or not all(finite(value) and value >= 0 for value in dimensions)):
            return None
        if all(abs(a-b) <= tolerance for a,b in zip(sorted(dimensions), sorted(expected))):
            return None
        considered.append({'object': name, 'dimensions_m': dimensions})
    return dict(policy=POLICY, failure_type='candidate_content',
                code='REQUIRED_FEATURE_BODY_ABSENT', within_tolerance=False,
                reason='Completed inspection contains no mesh with the declared feature-body dimensions',
                expected_object_dimensions_m=expected, tolerance_m=tolerance,
                unit_scale=scene['unit_scale'], inspected_meshes=considered,
                scope='This hole-pattern check only; retain all other partial scores')
