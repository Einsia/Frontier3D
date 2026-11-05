"""Animated asymmetrical body with actual constant or packed texture shading."""

from pathlib import Path

import bpy


def build(textured=False, animated_defect=False):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=.01)
    obj = bpy.context.object
    obj.name = 'part'
    obj.scale = (1, 1.5, 2)
    obj.keyframe_insert(data_path='location', frame=1)
    obj.keyframe_insert(data_path='rotation_euler', frame=1)
    obj.location = (.04, -.02, .03)
    obj.rotation_euler = (.35, -.23, .6)
    obj.keyframe_insert(data_path='location', frame=61)
    obj.keyframe_insert(data_path='rotation_euler', frame=61)
    for index, color in enumerate(((.2, .3, .4, 1), (.8, .1, .2, 1))):
        material = bpy.data.materials.new(f'material-{index}')
        material.use_nodes = True
        tree = material.node_tree
        shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Roughness'].default_value = .25 + index * .2
        shader.inputs['Metallic'].default_value = .3
        obj.data.materials.append(material)
        if animated_defect and index == 0:
            socket = shader.inputs['Roughness']
            socket.keyframe_insert(data_path='default_value', frame=1)
            socket.default_value = .9
            socket.keyframe_insert(data_path='default_value', frame=61)
    for face in obj.data.polygons:
        face.material_index = face.index % 2
    if textured:
        for version in ('base', 'changed'):
            image = bpy.data.images.new(version, width=4, height=4, alpha=True)
            image.colorspace_settings.name = 'Non-Color'
            pixels = []
            for y in range(4):
                for x in range(4):
                    pixels.extend((.9 if version == 'changed' else .1 + x / 5, .1 + y / 5, .2, 1))
            image.pixels.foreach_set(pixels)
            image.file_format = 'PNG'
            image.filepath_raw = str(Path.cwd() / f'{version}.png')
            image.save()
            bpy.data.images.remove(image)
            image = bpy.data.images.load(str(Path.cwd() / f'{version}.png'), check_existing=False)
            image.name = version
            image.colorspace_settings.name = 'sRGB'
            image.pack()
            image.use_fake_user = True
        for material in obj.data.materials:
            tree = material.node_tree
            shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
            texture = tree.nodes.new('ShaderNodeTexImage')
            texture.image = bpy.data.images['base']
            texture.interpolation = 'Linear'
            texture.extension = 'REPEAT'
            coordinates = tree.nodes.new('ShaderNodeUVMap')
            coordinates.uv_map = obj.data.uv_layers.active.name
            tree.links.new(coordinates.outputs['UV'], texture.inputs['Vector'])
            tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(Path.cwd() / 'scene.blend'))
    bpy.ops.export_scene.gltf(filepath=str(Path.cwd() / 'scene.glb'), export_format='GLB', export_animations=False)
