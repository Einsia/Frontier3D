"""Blender-only two-part animation fixtures; not mechanical task answers."""

from pathlib import Path

import bpy

root = Path.cwd()
for variant in ("good", "changed_native", "exploded_glb", "missing_part_glb"):
    destination = root / variant
    destination.mkdir()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=0.01)
    stationary = bpy.context.object
    stationary.name = "stationary"
    bpy.ops.mesh.primitive_cube_add(size=0.006)
    moving = bpy.context.object
    moving.name = "moving"
    moving.location = (0.02, 0, 0)
    moving.keyframe_insert(data_path="location", frame=1)
    moving.location = (0.06 if variant == "changed_native" else 0.04, 0, 0)
    moving.keyframe_insert(data_path="location", frame=61)
    bpy.context.scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(destination / "scene.blend"))
    bpy.context.scene.frame_set(61 if variant == "exploded_glb" else 1)
    # The GLTF exporter can sample an active action at its first frame even
    # when export_animations=False. Bake the selected pose into this static
    # export, after the animated native file has already been saved.
    moving.animation_data_clear()
    if variant == "missing_part_glb":
        bpy.data.objects.remove(moving, do_unlink=True)
    bpy.ops.export_scene.gltf(
        filepath=str(destination / "scene.glb"), export_format="GLB", export_animations=False,
    )
