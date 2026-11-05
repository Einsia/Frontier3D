"""Blender-side typed observations of effective Principled UV/image fields.

This parses data, never candidate Python. Unsupported conversions/graphs are
unavailable, not replaced by socket defaults. Surface comparison is separate.
"""

from __future__ import annotations

import json
import math

PROTOCOL = 'l1-material-field-v1'
MAX_DEPTH = 32
MAX_EXPRESSIONS = 4096


def _constant(socket):
    value = socket.default_value
    if socket.type in {'VALUE', 'BOOLEAN'}:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Nonfinite scalar socket')
        return result
    if socket.type not in {'RGBA', 'VECTOR'}:
        raise ValueError('Unsupported shader socket type')
    result = [float(item) for item in value][:3]
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        raise ValueError('Invalid shader vector/color socket')
    return result


class FieldParser:
    def __init__(self, capture, *, default_uv, uv_layers):
        self.capture = capture
        self.default_uv = default_uv
        self.uv_layers = set(uv_layers)
        self.images = {}
        self.count = 0

    def uv(self, name, *, binding='named_uv_map'):
        name = name or self.default_uv
        if not isinstance(name, str) or not name:
            raise ValueError('No default/named render UV layer')
        if name not in self.uv_layers:
            raise ValueError('Named render UV layer is absent')
        return {'op': 'uv', 'layer': name, 'binding': binding}

    def input(self, socket, *, seen=(), depth=0):
        if not socket.is_linked:
            return _constant(socket)
        if len(socket.links) != 1:
            raise ValueError('Shader input needs exactly one link')
        output = socket.links[0].from_socket
        if socket.type != output.type:
            raise ValueError('Implicit shader socket conversion is not calibrated')
        return self.output(output, seen=seen, depth=depth)

    def output(self, socket, *, seen=(), depth=0):
        self.count += 1
        if depth > MAX_DEPTH or self.count > MAX_EXPRESSIONS:
            raise ValueError('Shader expression depth/count limit')
        node = socket.node
        identity = node.as_pointer()
        if identity in seen or node.mute:
            raise ValueError('Cyclic or muted shader graph is unsupported')
        seen = (*seen, identity)
        def parse(value):
            return self.input(value, seen=seen, depth=depth + 1)
        if node.type in {'RGB', 'VALUE'}:
            return _constant(socket)
        if node.type == 'REROUTE':
            return parse(node.inputs[0])
        if node.type == 'UVMAP' and socket.name == 'UV':
            if node.from_instancer:
                raise ValueError('Instancer UV coordinates are unsupported')
            return self.uv(node.uv_map, binding='named_uv_map' if node.uv_map else 'default_uv')
        if node.type == 'TEX_COORD' and socket.name == 'UV':
            if node.from_instancer:
                raise ValueError('Instancer texture coordinates are unsupported')
            return self.uv(None, binding='default_uv')
        if node.type == 'TEX_IMAGE':
            if (node.projection != 'FLAT' or node.interpolation not in {'Linear', 'Closest'}
                    or node.extension not in {'REPEAT', 'EXTEND'} or socket.name not in {'Color', 'Alpha'}):
                raise ValueError('Uncalibrated image projection/filter/extension/output')
            image = self.capture.image(node.image)
            identifier = image['image_id']
            self.images[identifier] = image
            vector = parse(node.inputs['Vector']) if node.inputs['Vector'].is_linked else self.uv(None, binding='default_uv')
            return {'op': 'image', 'image': identifier, 'vector': vector, 'channel': socket.name,
                    'interpolation': node.interpolation, 'extension': node.extension,
                    '_node': identity, '_image': node.image.as_pointer()}
        if node.type in {'SEPARATE_COLOR', 'SEPRGB'}:
            if node.type == 'SEPARATE_COLOR' and node.mode != 'RGB':
                raise ValueError('Only RGB channel separation is calibrated')
            outputs = list(node.outputs)
            channel = next(index for index, value in enumerate(outputs) if value == socket)
            if channel > 2:
                raise ValueError('Unsupported separated color channel')
            return {'op': 'separate', 'value': parse(node.inputs[0]), 'channel': channel}
        if node.type == 'MATH' and node.operation in {'ADD', 'SUBTRACT', 'MULTIPLY', 'DIVIDE'}:
            return {'op': 'math', 'operation': node.operation, 'clamp': bool(node.use_clamp),
                    'inputs': [parse(node.inputs[0]), parse(node.inputs[1])]}
        raise ValueError(f'Unsupported effective shader node/output: {node.type}/{socket.name}')

    def finish(self, parameters):
        # Cycles deduplicates identical image lookup nodes. Alpha liveness must
        # be shared across an identical image/vector/filter expression, but not
        # across differently mapped/filtered lookups of the same image.
        images = []
        def walk(value):
            if isinstance(value, dict):
                if value.get('op') == 'image':
                    images.append(value)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(parameters)
        def key(value):
            # Named UVMap and implicit/TexCoord UV may sample identical values
            # but are distinct Cycles lookups. Preserve their binding kind.
            return json.dumps([value['_image'], value['vector'], value['interpolation'], value['extension']], sort_keys=True)
        alpha_lookups = {key(value) for value in images if value['channel'] == 'Alpha'}
        for value in images:
            value['alpha_used'] = key(value) in alpha_lookups
            value.pop('_node')
            value.pop('_image')
        return parameters


def describe_material_fields(material, *, capture, default_uv, uv_layers):
    record = {'status': 'not_measurable', 'material': getattr(material, 'name', None)}
    try:
        if material is None or not material.use_nodes or material.node_tree is None:
            raise ValueError('Explicit node-based Principled material required')
        outputs = [node for node in material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL'
                   and node.is_active_output and node.target == 'ALL']
        if len(outputs) != 1:
            raise ValueError('Exactly one active all-engine material output required')
        output = outputs[0]
        if output.inputs['Volume'].is_linked or output.inputs['Displacement'].is_linked:
            raise ValueError('Volume/displacement fields are unsupported')
        links = output.inputs['Surface'].links
        if len(links) != 1 or links[0].from_node.type != 'BSDF_PRINCIPLED' or links[0].from_node.mute:
            raise ValueError('Direct non-muted Principled surface output required')
        shader = links[0].from_node
        parser = FieldParser(capture, default_uv=default_uv, uv_layers=uv_layers)
        parameters = {socket.name: parser.input(socket) for socket in shader.inputs if socket.enabled}
        flags = {key: getattr(material, key) for key in ('use_backface_culling', 'surface_render_method',
                                                       'use_transparent_shadow') if hasattr(material, key)}
        flags.update(distribution=shader.distribution, subsurface_method=shader.subsurface_method)
        record.update(status='ok', kind='principled_uv_fields', parameters=parser.finish(parameters),
                      flags=flags, images=parser.images, parsed_expressions=parser.count,
                      semantics='cycles_cpu_filter_then_decode_v1')
    except (AttributeError, IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        record['reason'] = str(error)
    return record


def capture_material_fields(materials, *, capture, default_uv, uv_layers, used_slots):
    slots = []
    for index, material in enumerate(materials):
        slots.append(describe_material_fields(material, capture=capture, default_uv=default_uv, uv_layers=uv_layers)
                     if index in used_slots else {'status': 'unused'})
    return {'protocol': PROTOCOL, 'slots': slots,
            'scope': 'typed_principled_uv_image_and_scalar_expression_observation',
            'not_assessed': ['world_surface_field_equivalence', 'general_shader_groups',
                             'implicit_socket_conversions', 'bsdf_input_pruning_and_clamping',
                             'compiler_optimizations_outside_calibrated_lookup_deduplication', 'volumes_and_displacement',
                             'external_dependency_freezing_in_harness']}
