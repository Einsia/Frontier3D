"""Deterministic textured cube for real L1 resource-chain tests, not task quality."""

import json
from pathlib import Path

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=.01)
obj = bpy.context.object
image = bpy.data.images.new('external fixture', width=4, height=4, alpha=True)
image.pixels[:] = [.3, .6, .9, 1.] * 16
image.filepath_raw = str(Path.cwd() / 'albedo.png')
image.file_format = 'PNG'
image.save()
image = bpy.data.images.load(str(Path.cwd() / 'albedo.png'), check_existing=False)
image.filepath = '//albedo.png'
material = bpy.data.materials.new('textured fixture')
material.use_nodes = True
texture = material.node_tree.nodes.new('ShaderNodeTexImage')
texture.image = image
material.node_tree.links.new(texture.outputs['Color'], material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
obj.data.materials.append(material)
bpy.context.scene.frame_set(1)
bpy.ops.export_scene.gltf(filepath=str(Path.cwd() / 'scene.glb'), export_format='GLB')
bpy.ops.wm.save_as_mainfile(filepath=str(Path.cwd() / 'scene.blend'))
mode = json.loads(Path('mode.json').read_text())['mode']
if ((mode == 'missing_baseline' and Path.cwd().name == 'workspace')
        or (mode == 'missing_seed' and Path.cwd().name == '0')):
    Path('albedo.png').unlink()
