"""Animated asymmetric closed solids for real state-shape evidence."""

from pathlib import Path

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new('asymmetric')
mesh.from_pydata([(0, 0, 0), (.01, 0, 0), (0, .015, 0), (0, 0, .022)], [],
                 [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)])
mesh.update()
left = bpy.data.objects.new('left', mesh)
bpy.context.collection.objects.link(left)
bpy.ops.mesh.primitive_cube_add(size=.01, location=(.03, 0, 0))
bpy.context.object.name = 'right'
for obj, end in [(left, -.04), (bpy.context.object, .06)]:
    obj.keyframe_insert(data_path='location', frame=1)
    obj.location.x = end
    obj.keyframe_insert(data_path='location', frame=61)
    material = bpy.data.materials.new(obj.name)
    material.diffuse_color = (.2, .3, .4, 1)
    obj.data.materials.append(material)
bpy.context.scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str(Path.cwd() / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(Path.cwd() / 'scene.glb'), export_format='GLB', export_animations=False)
