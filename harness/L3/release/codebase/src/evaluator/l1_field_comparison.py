"""Diagnostic comparison of typed material inputs on corresponding surfaces.

Not a task hard gate: finite sampling, seams and renderer/parameter calibration
must be frozen per task before an observation upgrades formal coverage.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np

from .l1_shader_fields import PROTOCOL
from .l1_surface import load_surface
from .l1_surface_fields import interpolate_uv, sample_locations, surface_correspondence
from .l1_texture_fields import evaluate_field, load_texture, load_uv_layers

# Socket schema is tied to the exact build in l1_principled_fields, not to an
# arbitrary candidate-provided list (which could omit the changed parameter).
COMPILED_CHANNELS = {
    **dict.fromkeys(('Metallic', 'Roughness', 'IOR', 'Alpha', 'Thin Wall', 'Diffuse Roughness',
                     'Subsurface Weight', 'Subsurface Scale', 'Subsurface Anisotropy',
                     'Specular IOR Level', 'Anisotropic', 'Anisotropic Rotation', 'Transmission Weight',
                     'Coat Weight', 'Coat Roughness', 'Coat IOR', 'Sheen Weight', 'Sheen Roughness',
                     'Emission Strength', 'Thin Film Thickness', 'Thin Film IOR'), 1),
    **dict.fromkeys(('Base Color', 'Normal', 'Subsurface Radius', 'Specular Tint', 'Tangent',
                     'Coat Tint', 'Coat Normal', 'Sheen Tint', 'Emission Color'), 3),
}


def _compiled_channels(slot):
    from .l1_principled_fields import BUILD_HASH, RANGES, SEMANTICS
    from .l1_principled_fields import PROTOCOL as COMPILED_PROTOCOL

    if (not isinstance(slot, dict) or slot.get('protocol') != COMPILED_PROTOCOL or slot.get('status') != 'ok'
            or slot.get('hard_gate') is not False or slot.get('semantics') != SEMANTICS
            or slot.get('scope') != 'native_compiled_principled_input_fields'
            or slot.get('renderer') != {'version': [5, 2, 1], 'build_hash': BUILD_HASH, 'backend': 'CYCLES_CPU_SVM'}):
        raise ValueError('Unsupported or unbound compiled input slot')
    flags = slot['flags']
    if (not isinstance(flags, dict) or set(flags) != {'use_backface_culling', 'surface_render_method',
                                                    'use_transparent_shadow', 'distribution', 'subsurface_method'}
            or any(type(flags[key]) is not bool for key in ('use_backface_culling', 'use_transparent_shadow'))
            or any(not isinstance(flags[key], str) or not flags[key]
                   for key in ('surface_render_method', 'distribution', 'subsurface_method'))):
        raise ValueError('Incomplete compiled material flags')
    channels = dict(COMPILED_CHANNELS)
    if flags['subsurface_method'] == 'RANDOM_WALK_SKIN':
        channels['Subsurface IOR'] = 1
    if not isinstance(slot['parameters'], dict) or slot['parameters'].keys() != channels.keys():
        raise ValueError('Incomplete compiled input parameter schema')
    if not isinstance(slot.get('images'), dict):
        raise TypeError('Invalid compiled image table')
    normalizations = slot['normalizations']
    if (not isinstance(normalizations, dict) or normalizations.keys() != channels.keys() & RANGES.keys()
            or any(tuple(value) != RANGES[key] for key, value in normalizations.items())):
        raise ValueError('Untrusted compiled normalization schema')
    return channels


def _compiled_image_binding(image, root):
    """Pixel payload and its encoded source must belong to the same observation."""
    metadata = {key: image[key] for key in ('color_space', 'alpha_mode', 'image_is_float')}
    origin = image['origin']
    path = Path(origin['frozen_path'])
    if (image.get('status') != 'ok' or path.is_symlink() or not path.resolve().is_relative_to(root.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != origin['encoded_sha256']):
        raise ValueError('Frozen texture source missing, changed or outside trusted root')
    identifier = hashlib.sha256((origin['encoded_sha256'] + json.dumps(metadata, sort_keys=True)).encode()).hexdigest()
    if image['image_id'] != identifier:
        raise ValueError('Compiled image ID is not bound to encoded source and decode metadata')


def load_field_surface(item, trusted_root, *, compiled=False):
    from .l1_principled_fields import PROTOCOL as COMPILED_PROTOCOL

    root = Path(trusted_root)
    record = item['material_compiled_fields' if compiled else 'material_fields']
    if (record['protocol'] != (COMPILED_PROTOCOL if compiled else PROTOCOL)
            or record['geometry_sha256'] != item['mesh_payload']['sha256']
            or compiled and record.get('hard_gate') is not False):
        raise ValueError('Material field evidence protocol/geometry binding mismatch')
    surface = load_surface(item['mesh_payload'], root)
    assignment = record['assignment']
    if assignment['geometry_sha256'] != item['mesh_payload']['sha256']:
        raise ValueError('Field assignment bound to a different mesh')
    path = Path(assignment['path'])
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Field assignment escapes trusted root')
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != assignment['sha256']:
        raise ValueError('Field assignment hash mismatch')
    with np.load(io.BytesIO(content), allow_pickle=False) as data:
        if set(data.files) != {'triangle_material_indices'}:
            raise ValueError('Invalid field assignment members')
        indices = data['triangle_material_indices']
    slots = record['slots']
    if (not isinstance(slots, list) or indices.shape != (len(surface.triangles),) or indices.dtype.kind not in 'iu'
            or (indices < 0).any() or (indices >= len(slots)).any()):
        raise ValueError('Invalid field slot assignment')
    textures, texture_bindings = {}, {}
    for index in np.unique(indices):
        slot = slots[int(index)]
        if compiled:
            _compiled_channels(slot)
        elif (slot['status'] != 'ok' or slot['kind'] != 'principled_uv_fields'
                or slot['semantics'] != 'cycles_cpu_filter_then_decode_v1'
                or not isinstance(slot['parameters'], dict) or not slot['parameters'] or not isinstance(slot['flags'], dict)):
            raise ValueError('Unsupported or invalid effective field slot')
        for identifier, image in slot['images'].items():
            if identifier != image['image_id']:
                raise ValueError('Image field ID mismatch')
            signature = {key: image[key] for key in ('sha256', 'size', 'color_space', 'alpha_mode', 'image_is_float')}
            if identifier in texture_bindings and texture_bindings[identifier] != signature:
                raise ValueError('Conflicting pixel observations share an image ID')
            texture_bindings[identifier] = signature
            if compiled:
                _compiled_image_binding(image, root)
            textures[identifier] = load_texture(image, root)
    uv = load_uv_layers(item['surface_uv'], geometry_sha256=item['mesh_payload']['sha256'],
                        triangle_count=len(surface.triangles), trusted_root=root) if textures else {}
    binding = {'mesh': item['mesh_payload'], 'assignment': assignment,
               'slots_sha256': hashlib.sha256(json.dumps(slots, sort_keys=True, allow_nan=False).encode()).hexdigest(),
               'used_slots': [int(index) for index in np.unique(indices)],
               'textures': texture_bindings, 'uv': item.get('surface_uv') if textures else None}
    return {'mesh': surface, 'assignment': indices, 'slots': slots, 'textures': textures, 'uv': uv,
            'compiled': compiled, 'binding': binding}


def evaluate_locations(surface, triangles, barycentric):
    triangles = np.asarray(triangles)
    uv = interpolate_uv(surface['uv'], triangles, barycentric)
    assignments = surface['assignment'][triangles]
    values, flags = {}, [None] * len(triangles)
    for index in np.unique(assignments):
        mask = assignments == index
        slot = surface['slots'][int(index)]
        if values and values.keys() != slot['parameters'].keys():
            raise ValueError('Incompatible parameter sets across material regions')
        if surface.get('compiled'):
            from .l1_principled_fields import evaluate_parameters
            evaluated = evaluate_parameters(slot, textures=surface['textures'],
                                            uv_fields={name: data[mask] for name, data in uv.items()}, count=int(mask.sum()))
            channels = _compiled_channels(slot)
            if any(evaluated[key].shape != (int(mask.sum()), size) for key, size in channels.items()):
                raise ValueError('Invalid compiled parameter channel shape')
        else:
            evaluated = {key: evaluate_field(expression, textures=surface['textures'],
                                             uv_fields={name: data[mask] for name, data in uv.items()}, count=int(mask.sum()))
                         for key, expression in slot['parameters'].items()}
        for key, sampled in evaluated.items():
            if key not in values:
                values[key] = np.empty((len(triangles), sampled.shape[1]))
            if values[key].shape[1] != sampled.shape[1]:
                raise ValueError('Incompatible parameter channel shapes')
            values[key][mask] = sampled
        for position in np.flatnonzero(mask):
            flags[position] = slot['flags']
    return values, flags


def _uniform_literals(surface):
    """Prove constancy from every used slot, never from sampled colours.

    Expressions, textures and differing effective slots retain the general
    surface-field path. Actual compiled normalization still goes through the
    existing evaluator and its full renderer/channel/flag validation.
    """
    _, representatives = np.unique(surface['assignment'], return_index=True)
    for index in np.unique(surface['assignment']):
        slot = surface['slots'][int(index)]
        if slot['images'] or any(isinstance(value, dict) for value in slot['parameters'].values()):
            return None
    values, flags = evaluate_locations(surface, representatives, np.full((len(representatives), 3), 1/3))
    if (any(flag != flags[0] for flag in flags)
            or any(not np.array_equal(data, np.broadcast_to(data[0], data.shape)) for data in values.values())):
        return None
    return {key:data[0] for key,data in values.items()}, flags[0]


def _uniform_bound_directions(a, b, *, parameter_tolerance, surface_tolerance_m, levels):
    """Continuous geometry bound + all-used-slot constants, not sparse samples."""
    left, right = _uniform_literals(a), _uniform_literals(b)
    if left is None or right is None or len(levels) < 2:
        return None
    av, af = left
    bv, bf = right
    if av.keys() != bv.keys() or any(av[key].shape != bv[key].shape for key in av):
        raise ValueError('Incompatible uniform material field parameters')
    am, bm = a['mesh'], b['mesh']
    if am.vertices.shape == bm.vertices.shape and np.array_equal(am.triangles, bm.triangles):
        # Equal loaded connectivity gives a barycentric bijection even where
        # coincident vertices make nearest-vertex matching ambiguous.
        bound = float(np.linalg.norm(am.vertices-bm.vertices, axis=1).max())
        geometry_method = 'loaded_indexed_triangle_bijection'
    else:
        from .l1_rigid_shape import triangle_bound
        bound = triangle_bound(am, bm)
        geometry_method = 'loaded_nearest_vertex_triangle_bijection'
    if bound is None or bound > surface_tolerance_m:
        return None  # An upper bound above tolerance does not prove a failure.
    errors = {key:float(np.max(np.abs(av[key]-bv[key]))) for key in av}
    passed = af == bf and all(error <= parameter_tolerance for error in errors.values())
    return [{'direction':direction, 'status':'ok' if passed else 'failed',
        'method':'uniform_literal_fields_continuous_surface_bound_v1',
        'geometry_method':geometry_method, 'maximum_surface_distance_bound_m':bound,
        'parameter_maxima':errors.copy(), 'flags_equal':af == bf, 'ambiguous_samples':0,
        'samples_per_direction':0, 'sentinels':0, 'requested_levels':list(levels),
        'levels':[], 'converged':True, 'continuous_input_field_bound':True,
        'scope':'All used constant socket inputs and flags on bounded corresponding surfaces; not final BSDF equivalence'}
        for direction in ('left_to_right','right_to_left')]


def compare_material_fields(left, right, *, trusted_root, parameter_tolerance=1e-5,
                            surface_tolerance_m=1e-6, levels=(64, 256), seed=0, compiled=False,
                            pose_alignment=False, registration_convergence_m=1e-5):
    report = {'protocol': 'l1-material-field-comparison-v1', 'status': 'not_measurable', 'hard_gate': False,
              'alignment': 'none', 'scope': 'native_principled_input_fields', 'directions': [],
              'parameter_tolerance': parameter_tolerance, 'surface_tolerance_m': surface_tolerance_m,
              'limitations': ['Finite area samples plus face-center sentinels, not a continuous field bound',
                              'Ambiguous tied surface fields remain unavailable',
                              'Native input fields only; final shader clamping and glTF scope not normalized',
                              'BSDF input pruning and further compiler optimizations are not modeled',
                              'Task parameter/seam calibration and external dependency freezing incomplete']}
    if compiled:
        report.update(protocol='l1-compiled-field-comparison-v1', scope='native_compiled_principled_input_fields',
                      limitations=['Finite area samples and face centers, not a continuous field bound',
                                   'Ambiguous tied surface fields remain unavailable',
                                   'Compiled socket values, not final BSDF equivalence: inactive values may differ',
                                   'Shading normals/tangents, AOVs, general graphs and glTF normalization not assessed',
                                   'Task thresholds and seam/micro-region sampling remain uncalibrated'])
    try:
        if (type(compiled) is not bool or type(pose_alignment) is not bool or not levels or any(type(n) is not int or n <= 0 for n in levels)
                or list(levels) != sorted(set(levels)) or type(seed) is not int or seed < 0
                or any(isinstance(t, bool) or not np.isfinite(t) or t < 0 for t in (parameter_tolerance, surface_tolerance_m))):
            raise ValueError('Invalid field comparison sampling/tolerance configuration')
        a, b = (load_field_surface(item, trusted_root, compiled=compiled) for item in (left, right))
        report['inputs'] = {'left': a['binding'], 'right': b['binding']}
        if pose_alignment:
            from .l1_material_registration import register_material_surface
            moved, report['registration'] = register_material_surface(
                left, right, a['mesh'], b['mesh'], tolerance_m=surface_tolerance_m,
                levels=levels, convergence_m=registration_convergence_m, seed=seed)
            b = {**b, 'mesh': moved}
            report['alignment'] = 'pose_anchored_rigid_attachment'
        uniform = _uniform_bound_directions(a, b, parameter_tolerance=parameter_tolerance,
            surface_tolerance_m=surface_tolerance_m, levels=levels)
        if uniform is not None:
            report.update(directions=uniform, status=uniform[0]['status'],
                comparison_method='uniform_literal_fields_continuous_surface_bound_v1')
            report['limitations'] = [text for text in report['limitations']
                                    if not text.startswith(('Finite area samples','Ambiguous tied'))]
            report['limitations'].append('Continuous bound covers only spatially constant input fields, not full shaders')
            return report
        for direction, source, target, sample_seed in [('left_to_right', a, b, seed), ('right_to_left', b, a, seed + 1)]:
            sampled = sample_locations(source['mesh'], levels[-1], sample_seed)
            triangle_ids = np.concatenate((sampled['triangles'], np.arange(len(source['mesh'].triangles))))
            barycentric = np.concatenate((sampled['barycentric'], np.full((len(source['mesh'].triangles), 3), 1/3)))
            points = np.einsum('ij,ijk->ik', barycentric, source['mesh'].xyz[triangle_ids])
            source_values, source_flags = evaluate_locations(source, triangle_ids, barycentric)
            hits = surface_correspondence(points, target['mesh'])
            counts = np.array([len(hit['triangles']) for hit in hits])
            owner = np.repeat(np.arange(len(hits)), counts)
            target_values, target_flags = evaluate_locations(target, np.concatenate([h['triangles'] for h in hits]),
                                                             np.concatenate([h['barycentric'] for h in hits]))
            if source_values.keys() != target_values.keys():
                raise ValueError('Incompatible native material field parameter sets')
            errors = np.zeros(len(owner))
            parameter_errors = {}
            for key, values in source_values.items():
                if values.shape[1] != target_values[key].shape[1]:
                    raise ValueError('Incompatible native material field channels')
                differences = np.max(np.abs(values[owner] - target_values[key]), axis=1)
                parameter_errors[key] = float(differences.max())
                errors = np.maximum(errors, differences)
            flag_error = np.array([source_flags[i] != flag for i, flag in zip(owner, target_flags, strict=True)])
            offsets = np.concatenate(([0], np.cumsum(counts)))
            minimum, maximum, ambiguous = [], [], 0
            for position in range(len(hits)):
                begin, end = offsets[position:position + 2]
                local = errors[begin:end]
                valid = (local <= parameter_tolerance) & ~flag_error[begin:end]
                # A seam with both matching and mismatching equally near fields
                # has no unique correspondence; never silently choose a pass.
                ambiguous += int(valid.any() and not valid.all())
                minimum.append(float(local.min()))
                maximum.append(float(local.max()))
            minimum, maximum = np.asarray(minimum), np.asarray(maximum)
            distances = np.array([hit['distance_m'] for hit in hits])
            flags_all_wrong = [flag_error[offsets[i]:offsets[i+1]].all() for i in range(len(hits))]
            rows = []
            for level in levels:
                selected = np.concatenate((np.arange(level), np.arange(levels[-1], len(hits))))
                rows.append({'samples_per_direction': level, 'sentinels': len(source['mesh'].triangles),
                             'maximum_parameter_error': float(maximum[selected].max()),
                             'maximum_surface_distance_m': float(distances[selected].max())})
            mismatch = bool((minimum > parameter_tolerance).any() or (distances > surface_tolerance_m).any() or any(flags_all_wrong))
            converged = len(rows) > 1 and abs(rows[-1]['maximum_parameter_error'] - rows[-2]['maximum_parameter_error']) <= parameter_tolerance
            report['directions'].append({'direction': direction, 'levels': rows, 'ambiguous_samples': ambiguous,
                                         'parameter_maxima': parameter_errors,
                                         'converged': converged, 'status': 'failed' if mismatch else 'not_measurable'
                                         if ambiguous or not converged else 'ok'})
        statuses = [row['status'] for row in report['directions']]
        report['status'] = 'failed' if 'failed' in statuses else 'not_measurable' if 'not_measurable' in statuses else 'ok'
    except (KeyError, IndexError, TypeError, ValueError, OSError, FloatingPointError) as error:
        report['reason'] = str(error)
    return report


def compare_compiled_material_fields(left, right, **options):
    """Use only calibrated compiled observations, never fall back to raw fields."""
    return compare_material_fields(left, right, compiled=True, **options)
