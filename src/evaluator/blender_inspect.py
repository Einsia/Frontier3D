"""Blender worker that emits evaluator-owned scene facts and a canonical render."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def _arguments() -> argparse.Namespace:
    separator = sys.argv.index("--")
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--render", type=Path)
    return parser.parse_args(sys.argv[separator + 1 :])


def _object_facts(obj: bpy.types.Object) -> dict[str, object]:
    facts: dict[str, object] = {
        "name": obj.name,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "location": list(obj.matrix_world.translation),
        "dimensions": list(obj.dimensions),
        "visible_render": not obj.hide_render,
    }
    if obj.type == "MESH":
        mesh = obj.data
        bm = bmesh.new()
        bm.from_mesh(mesh)
        facts.update(
            {
                "vertices": len(mesh.vertices),
                "edges": len(mesh.edges),
                "faces": len(mesh.polygons),
                "nonmanifold_edges": sum(not edge.is_manifold for edge in bm.edges),
                "materials": [
                    material.name for material in mesh.materials if material is not None
                ],
            }
        )
        bm.free()
    if obj.type == "CAMERA":
        facts.update(
            {
                "camera_type": obj.data.type,
                "lens": obj.data.lens,
                "ortho_scale": obj.data.ortho_scale,
            }
        )
    return facts


def _scene_facts() -> dict[str, object]:
    scene = bpy.context.scene
    objects = [_object_facts(obj) for obj in scene.objects]
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    points = [
        obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box
    ]
    bounds = None
    dimensions = None
    if points:
        low = [min(point[index] for point in points) for index in range(3)]
        high = [max(point[index] for point in points) for index in range(3)]
        bounds = [low, high]
        dimensions = [high[index] - low[index] for index in range(3)]
    return {
        "blender_version": bpy.app.version_string,
        "object_count": len(objects),
        "mesh_count": len(meshes),
        "camera_count": sum(obj.type == "CAMERA" for obj in scene.objects),
        "light_count": sum(obj.type == "LIGHT" for obj in scene.objects),
        "material_count": len(bpy.data.materials),
        "global_bounds": bounds,
        "global_dimensions": dimensions,
        "unit_system": scene.unit_settings.system,
        "unit_scale": scene.unit_settings.scale_length,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "active_camera": scene.camera.name if scene.camera else None,
        "render": {
            "engine": scene.render.engine,
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "resolution_percentage": scene.render.resolution_percentage,
        },
        "objects": objects,
    }


def main() -> None:
    args = _arguments()
    scene_path = args.scene.expanduser().resolve()
    output = args.output.expanduser().resolve()
    bpy.ops.wm.open_mainfile(filepath=str(scene_path))
    facts = _scene_facts()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(facts, ensure_ascii=False, indent=2) + "\n")
    if args.render is not None:
        render = args.render.expanduser().resolve()
        render.parent.mkdir(parents=True, exist_ok=True)
        if bpy.context.scene.camera is None:
            raise RuntimeError("Candidate scene has no active camera")
        bpy.context.scene.render.filepath = str(render)
        bpy.context.scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - report every Blender worker failure
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    else:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
