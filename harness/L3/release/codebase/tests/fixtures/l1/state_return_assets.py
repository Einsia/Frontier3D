"""Two identical animated solids for restoration identity tests, not task answers."""

from pathlib import Path

import bpy

root = Path.cwd()
bpy.ops.wm.read_factory_settings(use_empty=True)
for name, start, finish in [('left', 0, -.02), ('right', .02, .04)]:
    bpy.ops.mesh.primitive_cube_add(size=.01)
    obj = bpy.context.object
    obj.name = name
    obj.location.x = start
    obj.keyframe_insert(data_path='location', frame=1)
    obj.location.x = finish
    obj.keyframe_insert(data_path='location', frame=61)
    material = bpy.data.materials.new(name)
    material.diffuse_color = (.2, .3, .4, 1)
    obj.data.materials.append(material)
bpy.context.scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'scene.blend'))
for obj in bpy.context.scene.objects:
    obj.animation_data_clear()
bpy.ops.export_scene.gltf(filepath=str(root / 'scene.glb'), export_format='GLB', export_animations=False)
