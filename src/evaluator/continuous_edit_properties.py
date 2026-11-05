"""Measure explicitly preserved native material and editable-part properties."""
import numpy as np
from scipy.optimize import linear_sum_assignment

from .continuous_numeric import scalar_error
from .continuous_surface import triangle_areas


FIELDS = ('Base Color', 'Metallic', 'Roughness', 'Alpha', 'IOR', 'Emission Strength')


def material_parameters(material):
    if material is None: return {name: None for name in FIELDS}
    settings = material['settings']
    if not settings.get('use_nodes'):
        return {'Base Color': settings['diffuse_color'], 'Metallic': settings['metallic'],
            'Roughness': settings['roughness'], 'Alpha': settings['diffuse_color'][3],
            'IOR': 1.5, 'Emission Strength': 0.}
    tree = material['nodes']; nodes, links = tree['nodes'], tree['links']
    outputs = [name for name,node in nodes.items() if node['type'] == 'ShaderNodeOutputMaterial'
               and node['properties'].get('is_active_output', True)]
    roots = [link[0] for link in links if link[2] in outputs and link[3] == 'Surface']
    roots = [name for name in roots if nodes[name]['type'] == 'ShaderNodeBsdfPrincipled']
    if len(roots) != 1: return {name: None for name in FIELDS}
    root = roots[0]; inputs = dict(nodes[root]['inputs'])
    linked = {link[3] for link in links if link[2] == root}
    return {name: inputs.get(name) if name not in linked else None for name in FIELDS}


def assignments(baseline, candidate):
    base = [o for o in baseline['objects'] if o.get('geometry')]
    cand = [o for o in candidate['objects'] if o.get('geometry')]
    if not base: raise ValueError('Protected public baseline has no geometric part')
    if not cand: return base, cand, {}
    centres_a = np.array([np.mean(o['bounds_m'], axis=0) for o in base])
    centres_b = np.array([np.mean(o['bounds_m'], axis=0) for o in cand])
    cost = np.linalg.norm(centres_a[:,None,:]-centres_b[None,:,:], axis=2)
    rows, columns = linear_sum_assignment(cost)
    return base, cand, {int(a): int(b) for a,b in zip(rows,columns)}


def preserve_properties(baseline, candidate, contract, evidence, load_material_geometry):
    """Area weights use assigned faces, independent of material/object names.

The caller verifies all source and mesh hashes. A changed procedural link is an
observed change to a baseline constant property and receives zero for that
property; other unchanged properties retain their measured contribution.
"""
    base, cand, mapping = assignments(baseline, candidate)
    settings = contract['protected_properties']
    materials, editability, records = [], [], []
    base_names = {o['object']: i for i,o in enumerate(base)}
    cand_names = {o['object']: i for i,o in enumerate(cand)}
    for index, original in enumerate(base):
        if index not in mapping:
            materials.append(0.); editability.append(0.)
            records.append({'baseline': original['object'], 'candidate': None, 'reason': 'Required editable part absent'})
            continue
        revised = cand[mapping[index]]
        original_parameters = [material_parameters(m) for m in original['materials']]
        # All current public CodeEdit parts have one uniform material. Multiple
        # original appearances require protected-face correspondence, not a
        # silent average over unrelated baseline slots.
        if not original_parameters or any(p != original_parameters[0] for p in original_parameters):
            raise ValueError('Protected baseline needs an explicit material region map')
        expected = original_parameters[0]
        if any(value is None for value in expected.values()):
            raise ValueError('Protected baseline has a nonconstant shader requiring a sampling contract')
        vertices, triangles, slots = load_material_geometry(revised['geometry'])
        areas = triangle_areas(vertices, triangles); total = float(areas.sum())
        if total <= 0: raise ValueError('No measurable candidate material surface')
        values, per_material = [], []
        for slot in np.unique(slots):
            fraction = float(areas[slots == slot].sum()/total)
            material = revised['materials'][slot] if 0 <= slot < len(revised['materials']) else None
            actual = material_parameters(material)
            quantities = []
            for field in FIELDS:
                if actual[field] is None:
                    value, errors = 0., None
                else:
                    errors = scalar_error(actual[field], expected[field], settings['material_tolerance'],
                                          settings['material_half_scale'])
                    value = float(np.exp2(-np.asarray(errors)).mean())
                quantities.append({'field': field, 'actual': actual[field], 'expected': expected[field],
                    'normalized_errors': errors, 'value': value,
                    'reason': 'Required constant shader parameter changed or absent' if errors is None else None})
            value = sum(q['value'] for q in quantities)/len(quantities)
            values.append(fraction*value)
            per_material.append({'slot': int(slot), 'surface_area_fraction': fraction, 'value': value, 'quantities': quantities})
        material_value = sum(values); materials.append(material_value)
        base_parent = base_names.get(original['parent'])
        cand_parent = cand_names.get(revised['parent'])
        expected_parent = mapping.get(base_parent) if base_parent is not None else None
        editable = float(bool(revised['editable']) and expected_parent == cand_parent)
        editability.append(editable)
        records.append({'baseline': original['object'], 'candidate': revised['object'],
            'baseline_parent_part': base_parent, 'candidate_parent_part': cand_parent,
            'editable': revised['editable'], 'independent_editability': editable,
            'material_value': material_value, 'materials': per_material})
    count_error = abs(len(base)-len(cand))
    groups = {'material_parameters': float(np.mean(materials)),
              'piece_count': float(2.**-count_error), 'independent_editability': float(np.mean(editability))}
    return {'status': 'measured', 'evidence': evidence, 'preserved_fraction': sum(groups.values())/len(groups),
        'groups': groups, 'parts': records, 'baseline_parts': len(base), 'candidate_parts': len(cand),
        'count_error': count_error, 'assignment': settings['part_assignment'], 'registration': 'none',
        'camera_preservation_applicable': settings['camera_preservation_applicable']}
