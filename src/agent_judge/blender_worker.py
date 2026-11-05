"""Fixed Blender inspection/render worker; no model-supplied Python is executed."""

import json
import hashlib
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


BUILTIN_NODES_SHA256 = '4592ec2a51b1adbd87467812979ddebb09f6606a49aa75549fdd2b40b7ffac86'
BUILTIN_NODES_RELATIVE = 'datafiles/assets/nodes/geometry_nodes_essentials.blend'


def restore_builtin_libraries():
    """Resolve only the identical Blender asset mounted by the generation runtime.

    Generation mounts this same Blender installation at /opt/blender. Copying
    an unchanged scene into a judge packet moves its relative library reference;
    its official asset remains part of the trusted runtime, not a task asset.
    No candidate file is rewritten and all other external dependencies stay
    subject to the packet boundary below.
    """
    if tuple(bpy.app.version) != (5, 2, 1):
        return [], set()
    target = (Path(bpy.utils.resource_path('LOCAL'))/BUILTIN_NODES_RELATIVE).resolve()
    container = '/opt/blender/5.2/'+BUILTIN_NODES_RELATIVE
    allowed = {container, '//../..'+container, str(target)}
    libraries = [library for library in bpy.data.libraries if library.filepath in allowed]
    if not libraries:
        return [], set()
    if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != BUILTIN_NODES_SHA256:
        raise ValueError('Trusted Blender geometry-node asset is missing or has changed')
    proof, reload_names = [], []
    for library in libraries:
        stored = library.filepath
        original = bpy.path.abspath(stored)
        linked = [{'name': block.name, 'type': block.bl_rna.identifier} for block in library.users_id]
        if linked:
            reload_names.append(library.name)
        library.filepath = str(target)
        proof.append({'stored_path': stored, 'original_resolved_path': original,
                      'runtime_path': str(target), 'sha256': BUILTIN_NODES_SHA256,
                      'blender_version': bpy.app.version_string, 'linked_datablocks': linked,
                      'scene_file_modified': False})
    # Reload may merge two references to this same file and invalidate their
    # Python RNA objects. Reacquire by name and then collect surviving pointers.
    for name in reload_names:
        library = bpy.data.libraries.get(name)
        if library is not None:
            library.reload()
    trusted = set()
    for library in bpy.data.libraries:
        if library.filepath == str(target):
            if library.is_missing:
                raise ValueError('Trusted Blender geometry-node library could not be reloaded')
            trusted.add(library.as_pointer())
    return proof, trusted


def main():
    request_path = Path(sys.argv[sys.argv.index("--") + 1])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source = Path(request["source"]).resolve()
    root = Path(request["asset_root"]).resolve()
    output = Path(request["output"])
    args = request["arguments"]
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    runtime_asset_remaps, trusted_libraries = restore_builtin_libraries()
    # Reject unresolved/out-of-packet dependencies instead of silently using host assets.
    # This is validation, not an OS sandbox: library loading may occur during open.
    dependencies = []
    # blend_paths also returns library_weak_reference provenance of APPENDED
    # (already local) meshes. Those source filenames are not runtime dependencies.
    datablocks = [
        *bpy.data.libraries,
        *bpy.data.images,
        *bpy.data.fonts,
        *bpy.data.sounds,
        *bpy.data.volumes,
        *bpy.data.cache_files,
    ]
    for asset in datablocks:
        if asset.as_pointer() in trusted_libraries:
            continue
        raw = getattr(asset, "filepath", "")
        if (
            not raw
            or raw == "<builtin>"
            or getattr(asset, "packed_file", None)
            or getattr(asset, "packed_files", None)
            or getattr(asset, "source", "FILE") in {"GENERATED", "VIEWER"}
        ):
            continue
        path = bpy.path.abspath(raw, library=asset.library)
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(root) or not resolved.exists():
            dependencies.append(path)
    if dependencies:
        raise ValueError(
            "Missing or external asset dependencies: " + repr(dependencies[:12])
        )
    scene = bpy.context.scene
    scene.frame_set(args.get("frame", 1))
    bpy.context.view_layer.update()
    objects = []
    for obj in scene.objects:
        item = {
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.matrix_world.translation),
            "dimensions": list(obj.dimensions),
            "hidden_render": obj.hide_render,
            "parent": obj.parent.name if obj.parent else None,
        }
        if obj.type == "MESH":
            item["vertices"] = len(obj.data.vertices)
            item["polygons"] = len(obj.data.polygons)
            item["materials"] = [m.name if m else None for m in obj.data.materials]
        objects.append(item)
    facts = {
        "blender_version": bpy.app.version_string,
        "runtime_asset_remaps": runtime_asset_remaps,
        "frame": scene.frame_current,
        "unit_scale_length": scene.unit_settings.scale_length,
        "active_camera": scene.camera.name if scene.camera else None,
        "objects": objects,
        "note": "Names, counts and bounds are structural evidence, not proof of semantic identity, holes or contact.",
    }
    if request["action"] == "render":
        camera_name = args.get("camera")
        if camera_name:
            camera = scene.objects.get(camera_name)
            if camera is None or camera.type != "CAMERA":
                raise ValueError("Unknown camera")
            scene.camera = camera
        else:
            focus = args.get("focus_objects", [])
            if any(name not in scene.objects for name in focus):
                raise ValueError("Unknown focus object")
            points = [
                obj.matrix_world @ Vector(point)
                for obj in scene.objects
                if obj.type == "MESH"
                and not obj.hide_render
                and (not focus or obj.name in focus)
                for point in obj.bound_box
            ]
            if not points:
                raise ValueError("No visible mesh in requested focus")
            low = Vector([min(p[i] for p in points) for i in range(3)])
            high = Vector([max(p[i] for p in points) for i in range(3)])
            center = Vector(args.get("target", list((low + high) / 2)))
            radius = max((high - low).length, 0.001)
            az, el = (
                math.radians(args.get("azimuth", -50)),
                math.radians(args.get("elevation", 30)),
            )
            direction = Vector(
                (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))
            )
            data = bpy.data.cameras.new("JudgeCamera")
            data.type = args.get("projection", "ORTHO")
            data.ortho_scale = radius * args.get("scale", 1.15)
            data.lens = 50
            data.clip_start, data.clip_end = max(radius / 1000, 1e-6), radius * 1000
            camera = bpy.data.objects.new("JudgeCamera", data)
            scene.collection.objects.link(camera)
            camera.location = center + direction * radius * args.get("distance", 3)
            camera.rotation_euler = (
                (center - camera.location).to_track_quat("-Z", "Y").to_euler()
            )
            scene.camera = camera
        if args.get("lighting", "authored") == "neutral":
            for obj in list(scene.objects):
                if obj.type == "LIGHT":
                    bpy.data.objects.remove(obj, do_unlink=True)
            world = bpy.data.worlds.new("JudgeNeutralWorld")
            world.use_nodes = True
            world.node_tree.nodes["Background"].inputs[0].default_value = (
                0.6,
                0.6,
                0.6,
                1,
            )
            world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
            scene.world = world
            data = bpy.data.lights.new("JudgeSun", "SUN")
            data.energy = 2
            light = bpy.data.objects.new("JudgeSun", data)
            scene.collection.objects.link(light)
            light.rotation_euler = (0.4, -0.5, -0.4)
        scene.render.engine = "CYCLES"
        scene.cycles.device, scene.cycles.samples, scene.cycles.seed = "CPU", 16, 0
        resolution = args.get("resolution", 768)
        if camera_name:
            # Preserve authored framing; changing aspect could invent clipping defects.
            factor = resolution / max(
                scene.render.resolution_x, scene.render.resolution_y
            )
            scene.render.resolution_x = max(
                1, round(scene.render.resolution_x * factor)
            )
            scene.render.resolution_y = max(
                1, round(scene.render.resolution_y * factor)
            )
        else:
            scene.render.resolution_x = scene.render.resolution_y = resolution
            scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.use_sequencer = False
        scene.use_nodes = False
        scene.render.film_transparent = False
        scene.render.filepath = str(output.with_suffix(".png"))
        bpy.context.view_layer.update()
        facts["view"] = {
            "arguments": args,
            "camera": scene.camera.name,
            "camera_matrix_world": [list(row) for row in scene.camera.matrix_world],
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "diagnostic": True,
            "note": "Custom framing/lighting is diagnostic; assess authored composition using authored cameras/images.",
        }
        bpy.ops.render.render(write_still=True)
    output.with_suffix(".json").write_text(
        json.dumps(facts, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
