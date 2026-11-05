"""Actual image content/UV/packing variants for L1 material-field tests.

All inputs are generated locally. No task references or external host assets.
"""

import json
from pathlib import Path

import bpy
import numpy as np

root = Path.cwd()
cases = ('base', 'rename', 'uv_layer_rename', 'triangulated', 'pixels_changed',
         'uv_shift', 'uv_integer_repeat', 'uv_flip', 'compensated_flip', 'external', 'missing_external',
         'closest', 'extend', 'alpha_pixels')
manifest = []
for variant in cases:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    directory = root / variant
    directory.mkdir()
    bpy.ops.mesh.primitive_cube_add(size=.01)
    obj = bpy.context.object
    obj.name = 'textured_part'
    mesh = obj.data
    uv = mesh.uv_layers.active
    for face in mesh.polygons:
        for loop, point in zip(face.loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1)), strict=True):
            uv.data[loop].uv = point
    values = np.array([[(x / 4 + .1, y / 4 + .1, (x + 2 * y) / 16 + .1, 1.)
                        for x in range(4)] for y in range(4)], dtype=np.float32)
    if variant == 'pixels_changed':
        values[1, 1, :3] = (.9, .05, .8)
    elif variant == 'compensated_flip':
        values = values[:, ::-1].copy()
    elif variant == 'alpha_pixels':
        values[..., 0] = .2
        values[..., 3] = np.array([.2, .4, .6, .8])[None, :]
    image = bpy.data.images.new('image-content', width=4, height=4, alpha=True)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels.foreach_set(values.reshape(-1))
    image.file_format = 'PNG'
    image.filepath_raw = str(directory / 'albedo.png')
    image.save()
    bpy.data.images.remove(image)
    image = bpy.data.images.load(str(directory / 'albedo.png'), check_existing=False)
    image.colorspace_settings.name = 'sRGB'
    if variant not in {'external', 'missing_external'}:
        image.pack()
    image.filepath = '//albedo.png'
    material = bpy.data.materials.new('textured_material')
    material.use_nodes = True
    mesh.materials.append(material)
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
    texture = tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.interpolation = 'Linear'
    texture.extension = 'REPEAT'
    if variant == 'closest':
        texture.interpolation = 'Closest'
    elif variant == 'extend':
        texture.extension = 'EXTEND'
    coordinates = tree.nodes.new('ShaderNodeUVMap')
    coordinates.uv_map = uv.name
    tree.links.new(coordinates.outputs['UV'], texture.inputs['Vector'])
    tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    if variant == 'rename':
        obj.name = 'renamed_part'
        material.name = 'renamed_material'
        image.name = 'renamed_image'
        texture.name = 'renamed_texture_node'
    if variant == 'uv_layer_rename':
        uv.name = 'renamed_uv'
        coordinates.uv_map = uv.name
    if variant in {'uv_shift', 'uv_integer_repeat', 'uv_flip', 'compensated_flip'}:
        for value in uv.data:
            value.uv.x = (1 - value.uv.x if variant in {'uv_flip', 'compensated_flip'}
                          else value.uv.x + (1 if variant == 'uv_integer_repeat' else .25))
    if variant == 'triangulated':
        modifier = obj.modifiers.new('new-triangulation', 'TRIANGULATE')
        modifier.quad_method = 'FIXED_ALTERNATE'
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'scene.blend'), relative_remap=False)
    if variant in {'base', 'external', 'compensated_flip'}:
        bpy.ops.export_scene.gltf(filepath=str(directory / 'scene.glb'), export_format='GLB', export_animations=False)
    if variant == 'missing_external':
        # Only the fixture-created file is moved; retain it for audit/recovery.
        (directory / 'albedo.png').rename(directory / 'albedo.missing-input.png')
    manifest.append({'variant': variant, 'packed': variant not in {'external', 'missing_external'},
                     'scene': str(directory / 'scene.blend'),
                     'expected': 'not_measurable' if variant == 'missing_external' else
                     'failed' if variant in {'pixels_changed', 'uv_shift', 'uv_flip', 'closest', 'extend', 'alpha_pixels'} else 'ok'})
(root / 'fixture-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
