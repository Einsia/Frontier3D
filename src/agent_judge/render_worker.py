"""Trusted Blender worker. Run only with --disable-autoexec; never candidate code.

L1 uses fixed orthographic views, neutral world/lights and frame 1/61.
L2 preserves the saved camera(s), materials and lighting as authored.
"""

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main():
    source, output, family, exploded = sys.argv[sys.argv.index("--") + 1 :]
    output = Path(output)
    bpy.ops.wm.open_mainfile(filepath=source, load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    scene.frame_set(1)
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.seed = 0
    scene.render.resolution_percentage = 100
    scene.render.resolution_x, scene.render.resolution_y = 900, 750
    scene.render.image_settings.file_format = "PNG"
    scene.use_nodes = False
    scene.render.use_sequencer = False
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    facts = {
        "blender_version": bpy.app.version_string,
        "unit_scale_length": scene.unit_settings.scale_length,
        "coordinate_units": "Blender native units; multiply lengths by unit_scale_length for metres",
        "frames": {},
    }

    def record(frame):
        scene.frame_set(frame)
        facts["frames"][str(frame)] = [
            {
                "name": o.name,
                "type": o.type,
                "location": list(o.matrix_world.translation),
                "dimensions": list(o.dimensions),
                "hidden_render": o.hide_render,
                "parent": o.parent.name if o.parent else None,
            }
            for o in scene.objects
            if o.type == "MESH"
        ]

    def render(name):
        scene.render.filepath = str(output / (name + ".png"))
        bpy.ops.render.render(write_still=True)

    record(1)
    if family == "Text2Code":
        for obj in list(scene.objects):
            if obj.type == "LIGHT":
                bpy.data.objects.remove(obj, do_unlink=True)
        world = bpy.data.worlds.new("JudgeNeutralWorld")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.6, 0.6, 0.6, 1)
        world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
        scene.world = world
        light_data = bpy.data.lights.new("JudgeSun", "SUN")
        light_data.energy = 2
        light = bpy.data.objects.new("JudgeSun", light_data)
        scene.collection.objects.link(light)
        light.rotation_euler = (0.4, -0.5, -0.4)
        camera_data = bpy.data.cameras.new("JudgeCamera")
        camera_data.type = "ORTHO"
        camera = bpy.data.objects.new("JudgeCamera", camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera
        for frame in sorted({1, int(exploded)}):
            record(frame)
            points = [
                o.matrix_world @ Vector(p)
                for o in scene.objects
                if o.type == "MESH" and not o.hide_render
                for p in o.bound_box
            ]
            if not points:
                raise ValueError("No visible mesh")
            low = Vector([min(p[i] for p in points) for i in range(3)])
            high = Vector([max(p[i] for p in points) for i in range(3)])
            center = (low + high) / 2
            radius = max((high - low).length, 0.001)
            camera_data.ortho_scale = radius * 1.15
            camera_data.clip_start = max(radius / 1000, 1e-6)
            camera_data.clip_end = radius * 100
            views = [
                ("assembled", (1.4, -1.8, 1.3)),
                ("front", (0, -2, 0.1)),
                ("top", (0, 0, 2)),
            ]
            if frame != 1:
                views = [("exploded", (1.4, -1.8, 1.3))]
            for name, direction in views:
                camera.location = center + Vector(direction).normalized() * radius * 3
                camera.rotation_euler = (
                    (center - camera.location).to_track_quat("-Z", "Y").to_euler()
                )
                render(name)
    else:
        cameras = [scene.camera] if scene.camera else []
        cameras += [o for o in scene.objects if o.type == "CAMERA" and o not in cameras]
        if not cameras:
            raise ValueError(
                "No authored camera; cannot silently invent Brief2Scene composition"
            )
        for i, camera in enumerate(cameras[:2]):
            scene.camera = camera
            render("main" if i == 0 else "alternate")
    (output / "scene_facts.json").write_text(
        json.dumps(facts, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
