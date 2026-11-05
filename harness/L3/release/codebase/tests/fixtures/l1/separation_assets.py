"""Real animated pairs: clearance, collective motion, penetration and a bore."""

import bpy


def build(mode):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if mode == 'hole':
        bpy.ops.mesh.primitive_torus_add(major_segments=16, minor_segments=8, major_radius=.01, minor_radius=.003)
        left = bpy.context.object
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=.004, depth=.04)
    else:
        bpy.ops.mesh.primitive_cube_add(size=.01)
        left = bpy.context.object
        bpy.ops.mesh.primitive_cube_add(size=.01, location=(.01, 0, 0))
    right = bpy.context.object
    left.name, right.name = 'left', 'right'
    for obj in (left, right):
        obj.keyframe_insert(data_path='location', frame=1)
        obj.keyframe_insert(data_path='scale', frame=1)
    if mode == 'separated':
        right.location.x = .025
    elif mode == 'diagonal':
        right.location = (.013, .014, 0)
    elif mode == 'collective':
        left.location.x += .03
        right.location.x += .03
    elif mode == 'overlapping':
        right.location.x = .009
    elif mode == 'contained':
        right.location.x = 0
        right.scale = (.25, .25, .25)
    elif mode == 'hole':
        right.location.z = .05
    elif mode != 'unchanged':
        raise ValueError(mode)
    for obj in (left, right):
        obj.keyframe_insert(data_path='location', frame=61)
        obj.keyframe_insert(data_path='scale', frame=61)
    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath='scene.blend')
    bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB', export_animations=False)
