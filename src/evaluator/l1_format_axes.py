"""Evidence-gated format conversion, never candidate-to-reference registration.

Only the inverse of Blender's glTF Y-up import conversion is supported. A
complete native/export vertex bijection and oriented triangle multiset equality
are required, exactly (no fitted tolerance, translation, scale or axis search).
This establishes format equivalence, not correctness of either delivered mesh.
"""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

from .l1_surface import SurfaceMesh, load_surface

PROTOCOL = 'l1-fixed-glb-format-axes-v1'
ROW_MATRIX = ((1, 0, 0), (0, 0, -1), (0, 1, 0))


def _faces(triangles):
    # Cyclic permutations preserve winding; reversal deliberately does not.
    return sorted(tuple(np.roll(row, -int(np.argmin(row)))) for row in triangles)


def prove_conversion(native: SurfaceMesh, imported: SurfaceMesh):
    if native.vertices.shape != imported.vertices.shape or native.triangles.shape != imported.triangles.shape:
        raise ValueError('Complete vertex and triangle populations must agree')
    if np.array_equal(native.vertices, imported.vertices):
        raise ValueError('No format-axis discrepancy to recover')
    transformed = imported.vertices @ np.asarray(ROW_MATRIX, dtype=np.float64)
    lookup = {tuple(vertex): i for i, vertex in enumerate(native.vertices)}
    if len(lookup) != len(native.vertices):
        raise ValueError('Ambiguous native vertex correspondence')
    try:
        mapping = np.asarray([lookup[tuple(vertex)] for vertex in transformed])
    except KeyError as error:
        raise ValueError('Fixed format conversion does not exactly match native vertices') from error
    if len(set(mapping)) != len(mapping):
        raise ValueError('Vertex mapping is not bijective')
    if _faces(native.triangles) != _faces(mapping[imported.triangles]):
        raise ValueError('Complete oriented triangle multisets differ')
    return transformed, {
        'protocol': PROTOCOL, 'fixed_row_vector_matrix': [list(r) for r in ROW_MATRIX],
        'mapping': '[x,y,z] imported -> [x,z,-y] task world metres',
        'max_vertex_error_m': 0.0, 'bijective_vertex_mapping': True,
        'every_oriented_triangle_matches': True, 'vertices': len(mapping),
        'triangles': len(imported.triangles), 'translation_m': [0, 0, 0], 'scale': 1,
        'optimized_registration': False, 'reference_geometry_used_for_conversion': False,
        'quality_pass_implied': False,
    }


def delivery_mesh(scene):
    objects = scene.get('objects', {})
    meshes = [(name, row) for name, row in objects.items() if row.get('type') == 'MESH']
    if (len(meshes) != 1 or meshes[0][1].get('entity_scope') != 'delivery_geometry'
            or scene.get('has_instances') or scene.get('unsupported_geometry')
            or any(r.get('entity_scope') == 'unsupported_delivery_geometry' for r in objects.values())):
        raise ValueError('One complete delivery mesh without unsupported geometry or instances required')
    return meshes[0]


def converted_numeric_scene(native_scene, imported_scene, *, trusted_root, output):
    """Write a new GLB-derived NPZ; retain original solid/editability verdicts.

    This minimal scene is ONLY for case-specific mesh numerical measurements;
    no material, camera, object transform or original inspector facts are edited.
    """
    _, native_record = delivery_mesh(native_scene)
    name, imported_record = delivery_mesh(imported_scene)
    native = load_surface(native_record['mesh_payload'], Path(trusted_root))
    imported = load_surface(imported_record['mesh_payload'], Path(trusted_root))
    transformed, proof = prove_conversion(native, imported)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        np.savez_compressed(stream, vertices_m=transformed, triangles=imported.triangles)
    import hashlib
    payload = {**copy.deepcopy(imported_record['mesh_payload']), 'path': str(output.resolve()),
               'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    record = {k: copy.deepcopy(imported_record[k]) for k in
              ('type', 'entity_scope', 'valid_solid', 'closed', 'components', 'editable')}
    record['mesh_payload'] = payload
    scene = {'objects': {name: record}, 'format_conversion': proof,
             'scope': 'mesh_numeric_only_not_a_replacement_for_original_inspection'}
    return scene, {**proof, 'native_mesh': copy.deepcopy(native_record['mesh_payload']),
                   'imported_mesh': copy.deepcopy(imported_record['mesh_payload']), 'converted_mesh': payload}
