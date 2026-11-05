"""Real Blender graph fixtures and field observation; calibration only."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--module', type=Path, required=True)
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
root = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


fields = module('shader_fields', args.module)
capture_module = module('texture_capture', root / 'src/evaluator/l1_texture_capture.py')
variants = ('base', 'default_uv', 'texcoord_uv', 'reroute', 'renamed_uv', 'separate_math',
            'alpha_live', 'alpha_dead', 'same_image_two_nodes', 'unsupported_mapping',
            'implicit_conversion', 'unsupported_group', 'muted', 'missing_uv', 'bad_uv',
            'math_div_zero', 'math_clamp', 'math_subtract', 'math_add', 'non_rgb_separate',
            'same_image_different_filter', 'same_image_different_uv',
            'same_image_default_uv', 'same_image_texcoord_uv')
rows = []
for variant in variants:
    directory = args.output / variant
    directory.mkdir(parents=True, exist_ok=True)
    source = args.assets / ('alpha_pixels' if variant.startswith(('alpha', 'same_image')) else 'base') / 'scene.blend'
    bpy.ops.wm.open_mainfile(filepath=str(source))
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH')
    material = obj.material_slots[0].material
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
    texture = next(node for node in tree.nodes if node.type == 'TEX_IMAGE')
    uv = next(node for node in tree.nodes if node.type == 'UVMAP')
    default_uv = obj.data.uv_layers.active.name
    if variant in {'default_uv', 'missing_uv'}:
        tree.links.remove(texture.inputs['Vector'].links[0])
        if variant == 'missing_uv':
            default_uv = None
            obj.data.uv_layers.remove(obj.data.uv_layers.active)
    elif variant == 'bad_uv':
        uv.uv_map = 'nonexistent'
    elif variant == 'texcoord_uv':
        node = tree.nodes.new('ShaderNodeTexCoord')
        tree.links.new(node.outputs['UV'], texture.inputs['Vector'])
    elif variant == 'reroute':
        node = tree.nodes.new('NodeReroute')
        tree.links.new(texture.outputs['Color'], node.inputs[0])
        tree.links.new(node.outputs[0], shader.inputs['Base Color'])
    elif variant == 'renamed_uv':
        obj.data.uv_layers.active.name = 'a different uv name'
        uv.uv_map = obj.data.uv_layers.active.name
        default_uv = uv.uv_map
    elif variant in {'separate_math', 'math_div_zero', 'math_clamp', 'math_subtract', 'math_add', 'non_rgb_separate'}:
        separate = tree.nodes.new('ShaderNodeSeparateColor')
        if variant == 'non_rgb_separate':
            separate.mode = 'HSV'
        tree.links.new(texture.outputs['Color'], separate.inputs['Color'])
        math_node = tree.nodes.new('ShaderNodeMath')
        math_node.operation = {'math_div_zero': 'DIVIDE', 'math_subtract': 'SUBTRACT', 'math_add': 'ADD'}.get(variant, 'MULTIPLY')
        math_node.inputs[1].default_value = 0 if variant == 'math_div_zero' else 2 if variant == 'math_clamp' else .5
        math_node.use_clamp = variant == 'math_clamp'
        tree.links.new(separate.outputs['Red'], math_node.inputs[0])
        tree.links.new(math_node.outputs[0], shader.inputs['Roughness'])
    elif variant in {'alpha_live', 'alpha_dead'} or variant.startswith('same_image'):
        node = texture
        if variant.startswith('same_image'):
            node = tree.nodes.new('ShaderNodeTexImage')
            node.image = texture.image
            tree.links.new(uv.outputs['UV'], node.inputs['Vector'])
            if variant == 'same_image_different_filter':
                node.interpolation = 'Closest'
            elif variant == 'same_image_default_uv':
                tree.links.remove(node.inputs['Vector'].links[0])
            elif variant == 'same_image_texcoord_uv':
                coordinates = tree.nodes.new('ShaderNodeTexCoord')
                tree.links.new(coordinates.outputs['UV'], node.inputs['Vector'])
            elif variant == 'same_image_different_uv':
                second_uv = obj.data.uv_layers.new(name='different_coords')
                for dst, src in zip(second_uv.data, obj.data.uv_layers[default_uv].data, strict=True):
                    dst.uv = (src.uv.x + .25, src.uv.y)
                coordinates = tree.nodes.new('ShaderNodeUVMap')
                coordinates.uv_map = second_uv.name
                tree.links.new(coordinates.outputs['UV'], node.inputs['Vector'])
        if variant == 'alpha_dead':
            unused = tree.nodes.new('ShaderNodeMath')
            tree.links.new(node.outputs['Alpha'], unused.inputs[0])
        else:
            tree.links.new(node.outputs['Alpha'], shader.inputs['Alpha'])
    elif variant == 'unsupported_mapping':
        node = tree.nodes.new('ShaderNodeMapping')
        tree.links.new(uv.outputs['UV'], node.inputs['Vector'])
        tree.links.new(node.outputs['Vector'], texture.inputs['Vector'])
    elif variant == 'implicit_conversion':
        tree.links.new(texture.outputs['Color'], shader.inputs['Roughness'])
    elif variant == 'unsupported_group':
        group = bpy.data.node_groups.new('unsupported_group', 'ShaderNodeTree')
        group.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        node = tree.nodes.new('ShaderNodeGroup')
        node.node_tree = group
        tree.links.new(node.outputs[0], shader.inputs['Base Color'])
    elif variant == 'muted':
        texture.mute = True
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'scene.blend'), relative_remap=False)
    capture = capture_module.TextureCapture(directory / 'images', resource_roots=[])
    record = fields.capture_material_fields([material], capture=capture, default_uv=default_uv,
                                            uv_layers=list(obj.data.uv_layers.keys()), used_slots={0})
    (directory / 'fields.json').write_text(json.dumps(record, indent=2))
    row = {'variant': variant, 'fields': str(directory / 'fields.json'), 'status': record['slots'][0]['status']}
    rows.append(row)
    if row['status'] != 'ok' or variant == 'bad_uv':
        continue
    # These controlled fixtures use identical UV on all cube faces. Bake into
    # the original layer without changing implicit texture coordinates; an
    # added atlas/explicit UV rewrite could change Cycles node deduplication.
    original_uv = obj.data.uv_layers[default_uv]
    obj.data.uv_layers.active = original_uv
    # Alpha use is determined independently from fixture construction, not from
    # parser output. Keep it live with Alpha/Alpha (=1 on these fixtures).
    color_socket = shader.inputs['Base Color'].links[0].from_socket
    alpha_socket = shader.inputs['Alpha'].links[0].from_socket if shader.inputs['Alpha'].is_linked else None
    rough_socket = shader.inputs['Roughness'].links[0].from_socket if shader.inputs['Roughness'].is_linked else None
    output = next(node for node in tree.nodes if node.type == 'OUTPUT_MATERIAL' and node.is_active_output)
    emission = tree.nodes.new('ShaderNodeEmission')
    tree.links.new(emission.outputs[0], output.inputs['Surface'])
    if alpha_socket is not None:
        guard = tree.nodes.new('ShaderNodeMath')
        guard.operation = 'DIVIDE'
        tree.links.new(alpha_socket, guard.inputs[0])
        tree.links.new(alpha_socket, guard.inputs[1])
        tree.links.new(guard.outputs[0], emission.inputs['Strength'])
    target = bpy.data.images.new('trusted_target', width=32, height=32, float_buffer=True)
    bake = tree.nodes.new('ShaderNodeTexImage')
    bake.image = target
    tree.nodes.active = bake
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.bake.margin = 0
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    arrays = {}
    trusted_uv = tree.nodes.new('ShaderNodeUVMap')
    trusted_uv.uv_map = default_uv
    for name, socket in [('Base Color', color_socket), ('Roughness', rough_socket), ('UV', trusted_uv.outputs['UV'])]:
        if socket is None:
            continue
        if name == 'Roughness':
            # Encode signed scalar values into positive emission; emission
            # itself is not an oracle for negative socket-input values.
            scale = tree.nodes.new('ShaderNodeMath')
            scale.operation = 'MULTIPLY'
            scale.inputs[1].default_value = .25
            tree.links.new(socket, scale.inputs[0])
            offset = tree.nodes.new('ShaderNodeMath')
            offset.operation = 'ADD'
            offset.inputs[1].default_value = .5
            tree.links.new(scale.outputs[0], offset.inputs[0])
            socket = offset.outputs[0]
        tree.links.new(socket, emission.inputs['Color'])
        bpy.ops.object.bake(type='EMIT')
        values = np.empty(32 * 32 * 4, dtype=np.float32)
        target.pixels.foreach_get(values)
        arrays[name] = values.reshape(32, 32, 4)
        if name == 'Roughness':
            arrays[name][..., :3] = (arrays[name][..., :3] - .5) / .25
    np.savez_compressed(directory / 'oracle.npz', **arrays)
    row['oracle'] = str(directory / 'oracle.npz')
(args.output / 'manifest.json').write_text(json.dumps(rows, indent=2) + '\n')
