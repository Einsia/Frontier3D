"""Continuous geometric support-chain measurement for Brief2Scene.

The result uses complete world-space triangles and published contact
tolerances. It records the actual contact predicates while keeping the
score kernel continuous through an explicit zero/one normalized error.
"""
import numpy as np

from .l2_support_chain import ContactBudget, Surface, assemble, contact


def _triangles(mesh):
    vertices, faces = mesh
    faces = np.asarray(faces, dtype=int)
    return np.asarray(vertices, dtype=float)[faces]


def _surface(entities, label):
    triangles = [_triangles(entity['mesh']) for entity in entities if len(entity['mesh'][1])]
    if not triangles:
        raise ValueError(f'Required {label} surface is absent')
    return Surface(np.concatenate(triangles))


def measure(check, roles, evidence):
    p = check['params']
    required = ('ground_role', 'support_role', 'rail_role', 'vehicle_role')
    if any(not roles.get(p[key]) for key in required):
        return {'status': 'measured', 'quantities': [{
            'status': 'absent', 'reason': 'A required support-chain role has no reviewed geometry'
        }], 'evidence': evidence, 'native_check': check, 'registration': 'none'}

    budget = ContactBudget()
    ground = _surface(roles[p['ground_role']], 'ground')
    rail = _surface(roles[p['rail_role']], 'rail')
    _, rail_detail = assemble(rail.xyz, p['contact_tolerance_m'], budget)
    rail_index = Surface(rail.xyz)
    support_rows = []
    signatures = set()
    for entity in roles[p['support_role']]:
        index = _surface([entity], 'support')
        _, detail = assemble(index.xyz, p['contact_tolerance_m'], budget)
        signature = tuple(np.round(np.r_[index.low, index.high], 6))
        duplicate = signature in signatures
        signatures.add(signature)
        grounded = contact(index, ground, p['contact_tolerance_m'], budget)
        attached = contact(index, rail_index, p['contact_tolerance_m'], budget)
        passed = bool(detail['connected'] and detail['non_coplanar'] and grounded and attached and not duplicate)
        support_rows.append({'entity': entity['id'], **detail, 'ground_contact': grounded,
                             'rail_contact': attached, 'duplicate_bounds': duplicate, 'passed': passed})
    vehicle_rows = []
    for entity in roles[p['vehicle_role']]:
        index = _surface([entity], 'rail vehicle')
        _, detail = assemble(index.xyz, p['contact_tolerance_m'], budget)
        attached = contact(index, rail_index, p['contact_tolerance_m'], budget)
        passed = bool(detail['connected'] and detail['non_coplanar'] and attached)
        vehicle_rows.append({'entity': entity['id'], **detail, 'rail_contact': attached, 'passed': passed})

    passed = bool(rail_detail['connected'] and rail_detail['non_coplanar']
                  and len([x for x in support_rows if x['passed']]) >= p['minimum_supports']
                  and all(x['passed'] for x in support_rows + vehicle_rows))
    return {'status': 'measured', 'quantities': [{
        'status': 'measured', 'normalized_errors': [0.0 if passed else 1e6],
        'unit': 'support_chain_verdict', 'passed': passed,
        'rail': rail_detail, 'supports': support_rows, 'vehicles': vehicle_rows,
        'complete_triangle_pairs_tested': budget.pairs,
        'contact_tolerance_m': p['contact_tolerance_m']
    }], 'evidence': evidence, 'native_check': check, 'registration': 'none',
        'coordinate_space': 'world_metres',
        'scope': 'Complete-surface contact and connected component checks for ground, supports, rail and vehicle',
        'limitations': 'Geometric contact does not infer load, strength, material identity or physical stability.'}
