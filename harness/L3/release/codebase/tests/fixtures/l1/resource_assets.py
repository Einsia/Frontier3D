"""Real .blend resource authority and render-scope variants; fixture-owned files."""
import json
import shutil
import sys
from pathlib import Path

import bpy

original, output = [Path(value).resolve() for value in sys.argv[sys.argv.index('--') + 1:]]
output.mkdir(parents=True)
variants = ('external', 'absolute', 'outside', 'symlink', 'directory_symlink', 'missing',
            'unused_node', 'unused_material', 'hidden_object', 'excluded_collection', 'object_override',
            'nested_group', 'render_only_modifier', 'hidden_viewport')
for variant in variants:
    directory = output / variant
    directory.mkdir()
    shutil.copy2(original / 'albedo.png', directory / 'albedo.png')
    bpy.ops.wm.open_mainfile(filepath=str(original / 'scene.blend'), load_ui=False, use_scripts=False)
    obj = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH')
    material = obj.material_slots[0].material
    texture = next(node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE')
    texture.image.filepath = '//albedo.png'
    shader = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    if variant == 'absolute':
        texture.image.filepath = str(directory / 'albedo.png')
    elif variant == 'outside':
        texture.image.filepath = str(original / 'albedo.png')
    elif variant == 'symlink':
        alias = directory / 'alias.png'
        alias.symlink_to(directory / 'albedo.png')
        texture.image.filepath = '//alias.png'
    elif variant == 'directory_symlink':
        alias = directory / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        texture.image.filepath = '//alias/albedo.png'
    elif variant == 'missing':
        texture.image.filepath = '//missing.png'
    elif variant == 'unused_node':
        other = texture.image.copy()
        other.filepath = '//missing.png'
        unused = material.node_tree.nodes.new('ShaderNodeTexImage')
        unused.image = other
    elif variant in {'unused_material', 'hidden_object', 'excluded_collection'}:
        unused = material.copy()
        bad_texture = next(node for node in unused.node_tree.nodes if node.type == 'TEX_IMAGE')
        bad_texture.image = texture.image.copy()
        bad_texture.image.filepath = '//missing.png'
        if variant == 'unused_material':
            obj.data.materials.append(unused)
        else:
            other = obj.copy()
            other.data = obj.data.copy()
            other.data.materials[0] = unused
            if variant == 'hidden_object':
                bpy.context.scene.collection.objects.link(other)
                other.hide_render = True
            else:
                collection = bpy.data.collections.new('not_rendered')
                bpy.context.scene.collection.children.link(collection)
                collection.objects.link(other)
                bpy.context.view_layer.layer_collection.children[collection.name].exclude = True
    elif variant == 'object_override':
        override = material.copy()
        obj.material_slots[0].link = 'OBJECT'
        obj.material_slots[0].material = override
        original_texture = next(node for node in material.node_tree.nodes if node.type == 'TEX_IMAGE')
        original_texture.image = texture.image.copy()
        original_texture.image.filepath = '//missing.png'
    elif variant == 'nested_group':
        tree = bpy.data.node_groups.new('image_group', 'ShaderNodeTree')
        tree.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        image = tree.nodes.new('ShaderNodeTexImage')
        image.image = texture.image
        output_node = tree.nodes.new('NodeGroupOutput')
        tree.links.new(image.outputs['Color'], output_node.inputs['Color'])
        group = material.node_tree.nodes.new('ShaderNodeGroup')
        group.node_tree = tree
        material.node_tree.links.new(group.outputs['Color'], shader.inputs['Base Color'])
    elif variant == 'render_only_modifier':
        # Assign an image material only when the render-enabled modifier is
        # evaluated. A viewport-only scan would miss the external dependency.
        original_material = bpy.data.materials.new('plain')
        original_material.use_nodes = True
        obj.data.materials[0] = original_material
        tree = bpy.data.node_groups.new('render_material', 'GeometryNodeTree')
        tree.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        tree.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        start, end = tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')
        apply = tree.nodes.new('GeometryNodeSetMaterial')
        apply.inputs['Material'].default_value = material
        tree.links.new(start.outputs['Geometry'], apply.inputs['Geometry'])
        tree.links.new(apply.outputs['Geometry'], end.inputs['Geometry'])
        modifier = obj.modifiers.new('render_only', 'NODES')
        modifier.node_group = tree
        modifier.show_viewport = False
        modifier.show_render = True
    elif variant == 'hidden_viewport':
        obj.hide_set(True)
        obj.hide_viewport = True
    bpy.context.scene.frame_set(17, subframe=.25)
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'scene.blend'), relative_remap=False)
(output / 'manifest.json').write_text(json.dumps(list(variants), indent=2))
