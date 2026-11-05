"""Two-material real cube variants; these are not answers to mechanical tasks."""

from pathlib import Path

import bpy

root = Path.cwd()
for variant in ('base', 'rename', 'reorder', 'duplicate', 'unused', 'triangulated', 'linked_constant',
                'roughness', 'metallic', 'faces', 'ior', 'missing_texture', 'nonconstant', 'backface',
                'unused_color_alpha', 'alpha', 'rerouted_constant', 'object_override_equivalent', 'object_override_changed'):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=.01)
    obj = bpy.context.object
    obj.name = 'part'
    for index, color in enumerate(((.2, .3, .4, 1), (.8, .1, .2, 1))):
        material = bpy.data.materials.new(f'material-{index}')
        material.use_nodes = True
        shader = next(node for node in material.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = .25 + index * .2
        shader.inputs['Metallic'].default_value = .3
        obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.material_index = polygon.index % 2
    material = obj.data.materials[0]
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
    if variant == 'rename':
        obj.name = 'renamed_part'
        for item in obj.data.materials:
            item.name = 'different-' + item.name
            for node in item.node_tree.nodes:
                node.name = 'different-' + node.name
                node.location.x += 100
    elif variant == 'reorder':
        first, second = obj.data.materials[:]
        obj.data.materials[0], obj.data.materials[1] = second, first
        for polygon in obj.data.polygons:
            polygon.material_index = 1 - polygon.material_index
    elif variant == 'duplicate':
        obj.data.materials.append(material.copy())
        obj.data.polygons[0].material_index = 2
    elif variant == 'unused':
        unused = material.copy()
        unused.node_tree.nodes.new('ShaderNodeTexNoise')
        obj.data.materials.append(unused)
        tree.nodes.new('ShaderNodeTexNoise')
    elif variant == 'triangulated':
        modifier = obj.modifiers.new('triangulate', 'TRIANGULATE')
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    elif variant in {'linked_constant', 'rerouted_constant'}:
        constant = tree.nodes.new('ShaderNodeValue')
        constant.outputs[0].default_value = .25
        if variant == 'rerouted_constant':
            reroute = tree.nodes.new('NodeReroute')
            tree.links.new(constant.outputs[0], reroute.inputs[0])
            tree.links.new(reroute.outputs[0], shader.inputs['Roughness'])
        else:
            tree.links.new(constant.outputs[0], shader.inputs['Roughness'])
    elif variant in {'roughness', 'metallic', 'ior'}:
        key = {'roughness': 'Roughness', 'metallic': 'Metallic', 'ior': 'IOR'}[variant]
        shader.inputs[key].default_value = 2 if variant == 'ior' else .9
    elif variant == 'faces':
        for polygon in obj.data.polygons:
            polygon.material_index = 1 - polygon.material_index
    elif variant in {'missing_texture', 'nonconstant'}:
        texture = tree.nodes.new('ShaderNodeTexImage' if variant == 'missing_texture' else 'ShaderNodeTexNoise')
        tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    elif variant == 'backface':
        material.use_backface_culling = True
    elif variant == 'unused_color_alpha':
        shader.inputs['Base Color'].default_value[3] = .2
    elif variant == 'alpha':
        shader.inputs['Alpha'].default_value = .4
    elif variant in {'object_override_equivalent', 'object_override_changed'}:
        override = material.copy()
        obj.material_slots[0].link = 'OBJECT'
        obj.material_slots[0].material = override
        if variant == 'object_override_equivalent':
            # The unused mesh slot changes, while actual object shading does not.
            shader.inputs['Roughness'].default_value = .9
        else:
            effective = next(node for node in override.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
            effective.inputs['Roughness'].default_value = .9
    directory = root / variant
    directory.mkdir()
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'scene.blend'))
    if variant == 'base':
        bpy.ops.export_scene.gltf(filepath=str(directory / 'scene.glb'), export_format='GLB', export_animations=False)
