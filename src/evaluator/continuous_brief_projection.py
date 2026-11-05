"""Continuous projected disjointness for Brief2Scene surfaces."""
import numpy as np

from .l2_projected_separation import ProjectionIndex


def _triangles(mesh):
    vertices, faces = mesh
    return np.asarray(vertices, dtype=float)[np.asarray(faces, dtype=int)]


def measure(check, roles, evidence):
    p = check['params']; selected = roles.get(p['role'], []); excluded = roles.get(p['excluded_role'], [])
    if not selected or not excluded:
        return {'status': 'measured', 'quantities': [{
            'status': 'absent', 'reason': 'Required projected role is absent'
        }], 'evidence': evidence, 'native_check': check, 'registration': 'none'}
    obstacle = ProjectionIndex(np.concatenate([_triangles(e['mesh']) for e in excluded]))
    budget = {'pairs': 0, 'maximum': 2_000_000}; rows = []
    for entity in selected:
        index = ProjectionIndex(_triangles(entity['mesh']))
        witness = index.intersects(obstacle, budget)
        rows.append({'entity': entity['id'], 'passed': witness is None,
                     'projected_triangles': len(index.triangles), 'overlap_witness': witness})
    passed = all(row['passed'] for row in rows)
    return {'status': 'measured', 'quantities': [{
        'status': 'measured', 'normalized_errors': [0.0 if passed else 1e6],
        'unit': 'projected_disjoint_verdict', 'passed': passed,
        'entities': rows, 'complete_candidate_pairs': budget['pairs']
    }], 'evidence': evidence, 'native_check': check, 'registration': 'none',
        'coordinate_space': 'world_metres',
        'scope': 'Complete selected XY surface projections; boundary contact has zero area and is allowed',
        'limitations': 'This predicate measures projected overlap and does not infer 3D penetration or clearance.'}
