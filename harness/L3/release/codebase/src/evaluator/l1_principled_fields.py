"""Compiled Principled input observation; not a material-equivalence gate.

Model Cycles link disconnection before image-output liveness. Disconnection
does not remove the input's constant/default value. Kernel numeric clamps are
separate: physically inactive compiled inputs can affect shared alpha handling.
"""

from __future__ import annotations

import importlib.util
import math
import struct
from pathlib import Path

_base_spec = importlib.util.spec_from_file_location('principled_shader_fields', Path(__file__).with_name('l1_shader_fields.py'))
_base = importlib.util.module_from_spec(_base_spec)
_base_spec.loader.exec_module(_base)
FieldParser, _constant = _base.FieldParser, _base._constant

PROTOCOL = 'l1-principled-effective-fields-v1'
BUILD_HASH = '9e2066aef7ef'
SEMANTICS = 'cycles_5_2_1_compiled_socket_values_v1'
UNKNOWN = object()


def f32(value):
    result = struct.unpack('f', struct.pack('f', float(value)))[0]
    if not math.isfinite(result):
        raise ValueError('Nonfinite compiled scalar')
    return result


CUTOFF = f32(1e-5)
RANGES = {
    **{name: (0., 1.) for name in ('Metallic', 'Roughness', 'Alpha', 'Diffuse Roughness',
                                  'Subsurface Weight', 'Transmission Weight', 'Anisotropic',
                                  'Coat Roughness', 'Sheen Roughness')},
    **{name: (0., None) for name in ('Base Color', 'Specular Tint', 'Specular IOR Level',
                                    'Coat Weight', 'Coat Tint', 'Sheen Weight', 'Sheen Tint')},
    'IOR': (1e-5, None), 'Coat IOR': (1., None),
}


def scalar_operation(operation, left, right):
    if operation == 'MULTIPLY':
        value = left * right
    elif operation == 'ADD':
        value = left + right
    elif operation == 'SUBTRACT':
        value = left - right
    elif operation == 'DIVIDE':
        value = left / right if right != 0 else 0.
    else:
        return UNKNOWN
    return f32(value)


def static_input(socket, *, seen=(), depth=0, budget=None):
    if not socket.is_linked:
        return _constant(socket)
    if len(socket.links) != 1 or socket.links[0].from_socket.type != socket.type:
        return UNKNOWN
    return static_output(socket.links[0].from_socket, seen=seen, depth=depth, budget=budget)


def static_output(socket, *, seen=(), depth=0, budget=None):
    budget = [4096] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError('Static shader expression count limit')
    node = socket.node
    if depth > 32 or node.as_pointer() in seen or node.mute:
        return UNKNOWN
    seen = (*seen, node.as_pointer())
    if node.type in {'RGB', 'VALUE'}:
        return _constant(socket)
    if node.type == 'REROUTE':
        return static_input(node.inputs[0], seen=seen, depth=depth + 1, budget=budget)
    if node.type != 'MATH' or node.operation not in {'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE'}:
        return UNKNOWN
    a, b = [static_input(value, seen=seen, depth=depth + 1, budget=budget) for value in node.inputs[:2]]
    def zero(value):
        return isinstance(value, (int, float)) and value == 0
    # Match the scalar host compiler, not algebraic/runtime safe-divide.
    # It prunes 0 / X but keeps X / 0 linked (unlike vector divide). The
    # latter's runtime zero still leaves image Alpha live in shared lookups.
    if (node.operation == 'MULTIPLY' and (zero(a) or zero(b))) or (node.operation == 'DIVIDE' and zero(a)):
        return 0.
    if a is UNKNOWN or b is UNKNOWN or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return UNKNOWN
    result = scalar_operation(node.operation, a, b)
    return min(max(result, 0.), 1.) if node.use_clamp else result


class CompiledFieldParser(FieldParser):
    def output(self, socket, *, seen=(), depth=0):
        value = static_output(socket, seen=seen, depth=depth)
        if value is not UNKNOWN:
            return value
        return super().output(socket, seen=seen, depth=depth)


def disconnected_inputs(shader):
    """Links removed by the host; socket values are NOT removed or zeroed."""
    inactive = set()
    def value(name):
        socket = shader.inputs.get(name)
        return static_input(socket) if socket is not None else UNKNOWN
    def below(name, *, inclusive=False):
        number = value(name)
        return isinstance(number, (int, float)) and (number <= CUTOFF if inclusive else number < CUTOFF)
    color = value('Emission Color')
    if below('Emission Strength', inclusive=True) or isinstance(color, list) and max(color) <= CUTOFF:
        inactive.update(('Emission Color', 'Emission Strength'))
    if value('Thin Wall') == 1.:
        inactive.update(('Subsurface Radius', 'Subsurface Scale', 'Subsurface IOR'))
    elif below('Subsurface Weight', inclusive=True) or value('Subsurface Scale') == 0.:
        inactive.update(('Subsurface Weight', 'Subsurface Radius', 'Subsurface Scale',
                         'Subsurface IOR', 'Subsurface Anisotropy'))
    for weight, dependents in {
        'Coat Weight': ('Coat Roughness', 'Coat IOR', 'Coat Tint'),
        'Sheen Weight': ('Sheen Roughness', 'Sheen Tint'),
        'Anisotropic': ('Anisotropic Rotation', 'Tangent'),
        'Thin Film Thickness': ('Thin Film IOR',),
    }.items():
        if below(weight):
            inactive.update((weight, *dependents))
    # In particular, host pruning keeps Coat Normal even at zero coat weight.
    # It also does not prune Transmission Weight at Metallic=1 or Thin Film
    # IOR below the *kernel* 0.1 nm cutoff; their lookups can remain compiled.
    return inactive


def compiled_input(socket, disconnected, parser):
    if socket.name not in disconnected:
        return parser.input(socket)
    # Constant folding sets the socket value before simplify_settings. When a
    # surviving nonconstant link is disconnected, its authored default value
    # remains. Even a tiny emission strength can still contribute at runtime.
    value = static_input(socket)
    return _constant(socket) if value is UNKNOWN else value


def socket_available(shader, socket):
    # The evaluated material copy can lose the unavailable bit. Reconstruct
    # this node's only method-dependent availability from its actual enum,
    # matching node_shader_update_principled for the calibrated build.
    if socket.name == 'Subsurface IOR':
        return shader.subsurface_method == 'RANDOM_WALK_SKIN'
    return not socket.is_unavailable


def describe_principled(material, *, capture, default_uv, uv_layers):
    result = {'protocol': PROTOCOL, 'status': 'not_measurable', 'hard_gate': False,
              'scope': 'native_compiled_principled_input_fields',
              'not_assessed': ['full_bsdf_closure_equivalence', 'shading_normals_and_tangents',
                               'glTF_scope_normalization', 'general_shader_graphs',
                               'task_thresholds_and_surface_sampling', 'material_output_aovs']}
    try:
        import bpy
        build = bpy.app.build_hash.decode()
        result['renderer'] = {'version': list(bpy.app.version), 'build_hash': build, 'backend': 'CYCLES_CPU_SVM'}
        if build != BUILD_HASH or tuple(bpy.app.version) != (5, 2, 1):
            raise ValueError('Compiled Principled policy requires its calibrated Blender build')
        if material is None or not material.use_nodes or material.node_tree is None:
            raise ValueError('Explicit node-based Principled material required')
        if any(node.type == 'OUTPUT_AOV' for node in material.node_tree.nodes):
            raise ValueError('AOV outputs can change shared image liveness; not yet calibrated')
        outputs = [node for node in material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL'
                   and node.is_active_output and node.target == 'ALL']
        if len(outputs) != 1:
            raise ValueError('One active all-engine output required')
        output = outputs[0]
        if output.inputs['Volume'].is_linked or output.inputs['Displacement'].is_linked:
            raise ValueError('Volume/displacement remains unassessed')
        links = output.inputs['Surface'].links
        if len(links) != 1 or links[0].from_node.type != 'BSDF_PRINCIPLED' or links[0].from_node.mute:
            raise ValueError('Direct non-muted Principled surface required')
        shader = links[0].from_node
        inactive = disconnected_inputs(shader)
        parser = CompiledFieldParser(capture, default_uv=default_uv, uv_layers=uv_layers)
        parameters = {socket.name: compiled_input(socket, inactive, parser) for socket in shader.inputs
                      if socket_available(shader, socket)}
        parameters = parser.finish(parameters)
        flags = {key: getattr(material, key) for key in ('use_backface_culling', 'surface_render_method',
                                                       'use_transparent_shadow') if hasattr(material, key)}
        flags.update(distribution=shader.distribution, subsurface_method=shader.subsurface_method)
        result.update(status='ok', parameters=parameters, images=parser.images, flags=flags,
                      disconnected_inputs=sorted(inactive), normalizations={name: RANGES[name] for name in parameters if name in RANGES},
                      semantics=SEMANTICS)
    except (AttributeError, IndexError, KeyError, OSError, OverflowError, RuntimeError, TypeError, ValueError) as error:
        result['reason'] = str(error)
    return result


def capture_principled_fields(materials, *, capture, default_uv, uv_layers, used_slots):
    return {'protocol': PROTOCOL, 'hard_gate': False,
            'scope': 'native_compiled_principled_input_fields',
            'slots': [describe_principled(material, capture=capture, default_uv=default_uv, uv_layers=uv_layers)
                      if index in used_slots else {'status': 'unused'}
                      for index, material in enumerate(materials)]}


def evaluate_parameters(record, *, uv_fields, textures, count):
    import numpy as np

    from src.evaluator.l1_texture_fields import evaluate_field
    if record.get('protocol') != PROTOCOL or record.get('status') != 'ok':
        raise ValueError('Effective Principled record unavailable')
    if record['renderer'] != {'version': [5, 2, 1], 'build_hash': BUILD_HASH, 'backend': 'CYCLES_CPU_SVM'}:
        raise ValueError('Wrong calibrated renderer binding')
    if record['semantics'] != SEMANTICS:
        raise ValueError('Unknown compiled input semantics')
    values = {}
    for name, expression in record['parameters'].items():
        raw = evaluate_field(expression, uv_fields=uv_fields, textures=textures, count=count)
        expected = RANGES.get(name)
        actual = record['normalizations'].get(name)
        if (tuple(actual) if actual is not None else None) != expected:
            raise ValueError('Untrusted parameter normalization override')
        values[name] = np.clip(raw, *expected) if expected is not None else raw
    return values
