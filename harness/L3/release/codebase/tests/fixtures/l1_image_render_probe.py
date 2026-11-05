"""Independent procedural scene for saved-render tests; no private inputs."""
import sys
from pathlib import Path

import bpy
from mathutils import Vector

root = Path(sys.argv[sys.argv.index('--') + 1])
root.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=.45)
obj = bpy.context.object
material = bpy.data.materials.new('ProceduralColour')
material.use_nodes = True
material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.4, .06, .02, 1)
obj.data.materials.append(material)
bpy.ops.object.camera_add(location=(2, -3, 2))
scene = bpy.context.scene
scene.camera = bpy.context.object
scene.camera.rotation_euler = (-scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera.data.type = 'PERSP'
bpy.ops.object.light_add(type='AREA', location=(0, -2, 3))
bpy.context.object.data.energy = 500
bpy.context.object.data.size = 2
bpy.context.object.rotation_euler = (Vector((0, 0, 0))-bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
scene.render.engine = 'CYCLES'
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.cycles.use_adaptive_sampling = False
scene.render.resolution_x = scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.view_settings.view_transform = 'AgX'
scene.render.filepath = str(root / 'main.png')
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'valid.blend'))
bpy.ops.render.render(write_still=True)
obj.scale.x = .3
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'different.blend'))
obj.scale.x = 1
scene.sequence_editor_create().strips.new_image('Image bypass', str(root / 'main.png'), channel=1, frame_start=1)
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'sequencer.blend'))
scene.sequence_editor_clear()
scene.render.resolution_percentage = 50
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'halfsize.blend'))
