"""Independent Blender worker: evaluated meshes, probes and fixed views.

Executed as a file by Blender. No candidate annotations, cameras, compositor,
materials or submitted images are used to construct geometric silhouettes.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
import traceback
import uuid
import zlib
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

_MESH_KERNEL = None
_MATERIAL_PROBE = None
_TEXTURE_PROBE = None
_SHADER_FIELDS = None
_PRINCIPLED_FIELDS = None
_PROCEDURAL_MATERIALS = None
_NON_GEOMETRIC_TYPES = {
    "EMPTY",
    "CAMERA",
    "LIGHT",
    "ARMATURE",
    "LATTICE",
    "SPEAKER",
    "LIGHT_PROBE",
}


def _mesh_kernel():
    global _MESH_KERNEL
    if _MESH_KERNEL is None:
        # Load a fixed evaluator-owned sibling, never a candidate's import path.
        spec = importlib.util.spec_from_file_location(
            "l1_mesh", Path(__file__).with_name("l1_mesh.py")
        )
        _MESH_KERNEL = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MESH_KERNEL)
    return _MESH_KERNEL


def _face_area(face):
    # Blender's float32 polygon formula can cancel a thin, nondegenerate
    # exported triangle to zero. Keep the original 1e-18 m² threshold.
    if len(face.verts) == 3:
        return _mesh_kernel().triangle_area([vertex.co for vertex in face.verts])
    return face.calc_area()


def _material_probe():
    global _MATERIAL_PROBE
    if _MATERIAL_PROBE is None:
        spec = importlib.util.spec_from_file_location(
            "l1_material_probe", Path(__file__).with_name("l1_material_probe.py")
        )
        _MATERIAL_PROBE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_MATERIAL_PROBE)
    return _MATERIAL_PROBE


def _texture_probe():
    global _TEXTURE_PROBE
    if _TEXTURE_PROBE is None:
        spec = importlib.util.spec_from_file_location(
            'l1_texture_capture', Path(__file__).with_name('l1_texture_capture.py')
        )
        _TEXTURE_PROBE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_TEXTURE_PROBE)
    return _TEXTURE_PROBE


def _shader_fields():
    global _SHADER_FIELDS
    if _SHADER_FIELDS is None:
        spec = importlib.util.spec_from_file_location(
            'l1_shader_fields', Path(__file__).with_name('l1_shader_fields.py')
        )
        _SHADER_FIELDS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_SHADER_FIELDS)
    return _SHADER_FIELDS


def _principled_fields():
    global _PRINCIPLED_FIELDS
    if _PRINCIPLED_FIELDS is None:
        spec = importlib.util.spec_from_file_location(
            'l1_principled_fields', Path(__file__).with_name('l1_principled_fields.py')
        )
        _PRINCIPLED_FIELDS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PRINCIPLED_FIELDS)
    return _PRINCIPLED_FIELDS


def _procedural_materials():
    global _PROCEDURAL_MATERIALS
    if _PROCEDURAL_MATERIALS is None:
        spec = importlib.util.spec_from_file_location(
            "l1_procedural_materials", Path(__file__).with_name("l1_procedural_materials.py")
        )
        _PROCEDURAL_MATERIALS = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_PROCEDURAL_MATERIALS)
    return _PROCEDURAL_MATERIALS


def _solid_audit(
    bm, facts: dict, policy: dict, payload_path: Path | None = None
) -> None:
    bm.verts.index_update()
    loops = bm.calc_loop_triangles()
    if len(loops) > policy["max_triangles"]:
        raise WorkerFailure(
            "not_implemented",
            "MESH_AUDIT_LIMIT",
            "Triangle count exceeds inspector resource limit",
        )
    vertices = [tuple(v.co) for v in bm.verts]
    triangles = [tuple(loop.vert.index for loop in triangle) for triangle in loops]
    facts["triangles"] = len(triangles)
    facts["bmesh_signed_volume_integral_m3"] = facts["signed_volume_integral_m3"]
    facts["signed_volume_integral_m3"] = _mesh_kernel().triangulated_volume(
        vertices, triangles
    )
    facts["loose_vertices"] = sum(not v.link_faces for v in bm.verts)
    facts["loose_edges"] = sum(not e.link_faces for e in bm.edges)
    canonical = {tuple(sorted(t)) for t in triangles}
    if len(canonical) != len(triangles):
        # Duplicate triangles already prove invalidity. Avoid a quadratic BVH
        # overlap allocation on coincident duplicate-heavy candidate meshes.
        intersections = {
            "status": "ok",
            "candidate_pairs": None,
            "intersecting_pairs": len(triangles) - len(canonical),
            "examples": [],
            "method": "duplicate_triangle_rejection",
            "count_is_lower_bound": True,
        }
    elif not triangles:
        intersections = {
            "status": "ok",
            "candidate_pairs": 0,
            "intersecting_pairs": 0,
            "examples": [],
        }
    else:
        tree = BVHTree.FromPolygons(
            vertices,
            triangles,
            all_triangles=True,
            epsilon=policy["intersection_epsilon_m"],
        )
        intersections = _mesh_kernel().intersection_audit(
            vertices,
            triangles,
            tree.overlap(tree),
            policy["intersection_epsilon_m"],
            policy["max_intersection_pairs"],
        )
        if intersections["status"] != "ok":
            raise WorkerFailure(
                "not_implemented", "MESH_AUDIT_LIMIT", intersections["reason"]
            )
    facts["self_intersection"] = intersections
    facts.update(_mesh_kernel().solid_validity(facts, intersections))
    if payload_path is not None:
        import numpy as np

        payload_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            payload_path,
            vertices_m=np.asarray(vertices, dtype=np.float64),
            triangles=np.asarray(triangles, dtype=np.int64),
        )
        facts["mesh_payload"] = {
            "path": str(payload_path),
            "coordinate_space": "world_metres",
            "sha256": hashlib.sha256(payload_path.read_bytes()).hexdigest(),
            "triangulation": "evaluated_welded_bmesh_loop_triangles",
        }
        if "material_surface" in facts:
            assignment_path = payload_path.with_name(payload_path.stem + "-materials.npz")
            np.savez_compressed(assignment_path, triangle_material_indices=np.asarray(
                [triangle[0].face.material_index for triangle in loops], dtype=np.int64,
            ))
            facts["material_surface"]["assignment"] = {
                "path": str(assignment_path),
                "sha256": hashlib.sha256(assignment_path.read_bytes()).hexdigest(),
                "geometry_sha256": facts["mesh_payload"]["sha256"],
            }
            if 'material_fields' in facts:
                facts['material_fields']['assignment'] = dict(facts['material_surface']['assignment'])
                facts['material_fields']['geometry_sha256'] = facts['mesh_payload']['sha256']
            if 'material_compiled_fields' in facts:
                facts['material_compiled_fields']['assignment'] = dict(facts['material_surface']['assignment'])
                facts['material_compiled_fields']['geometry_sha256'] = facts['mesh_payload']['sha256']
        if facts.get('material_textures', {}).get('observations'):
            facts['material_textures']['geometry_sha256'] = facts['mesh_payload']['sha256']
            try:
                facts['surface_uv'] = _texture_probe().capture_uv_layers(
                    bm, loops, payload_path=payload_path, geometry_sha256=facts['mesh_payload']['sha256'],
                    default_layer=facts.get('default_render_uv_layer'),
                )
            except ValueError as error:
                facts['surface_uv'] = {'protocol': 'l1-surface-uv-v1', 'status': 'not_measurable', 'reason': str(error)}


class WorkerFailure(RuntimeError):
    def __init__(self, status: str, code: str, reason: str):
        self.status, self.code, self.reason = status, code, reason
        super().__init__(reason)


def _bounds(
    points: list[Vector],
) -> tuple[list[list[float]] | None, list[float] | None]:
    if not points:
        return None, None
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return [low, high], [high[i] - low[i] for i in range(3)]


def _components(bm: bmesh.types.BMesh) -> int:
    remaining = set(bm.verts)
    count = 0
    while remaining:
        stack = [remaining.pop()]
        count += 1
        while stack:
            for edge in stack.pop().link_edges:
                for neighbor in edge.verts:
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
    return count


def _material_color_evidence(materials) -> dict:
    """Observe constant shader base colors, separately from viewport proxies.

    General graphs/textures are deliberately unavailable here. This is not a
    canonical material or face-assignment representation.
    """
    slots = []
    for material in materials:
        if material is None:
            continue
        item = {"material": material.name, "status": "not_measurable"}
        slots.append(item)
        if not material.use_nodes:
            item.update(status="ok", source="non_node_diffuse", color=list(material.diffuse_color))
            continue
        tree = material.node_tree
        outputs = [] if tree is None else [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"
                                           and node.is_active_output and node.target == "ALL"]
        if len(outputs) != 1 or len(outputs[0].inputs["Surface"].links) != 1:
            item["reason"] = "A single active all-engine material Surface output is required"
            continue
        link = outputs[0].inputs["Surface"].links[0]
        shader = link.from_node
        if shader.type != "BSDF_PRINCIPLED" or link.from_socket.name != "BSDF":
            item["reason"] = "Only direct constant Principled base colors are supported"
            continue
        color, alpha = shader.inputs.get("Base Color"), shader.inputs.get("Alpha")
        if color is None or alpha is None or color.is_linked or alpha.is_linked:
            item["reason"] = "Linked base color/alpha requires graph or texture evaluation"
            continue
        rgba = list(color.default_value)
        rgba[3] = float(alpha.default_value)
        item.update(status="ok", source="principled_constant", color=rgba)
    available = all(item["status"] == "ok" for item in slots)
    return {"protocol": "l1-material-color-v1", "status": "ok" if available else "not_measurable",
            "colors": [item["color"] for item in slots] if available else None, "slots": slots,
            "scope": "constant_base_color_rgba_only",
            "not_assessed": ["other_shader_parameters", "general_node_graphs", "textures", "face_assignments"]}


def _surface_mesh_signature(mesh):
    """Exact evaluated geometry/material assignment identity, without alignment."""
    digest = hashlib.sha256()
    for vertex in mesh.vertices:
        digest.update(struct.pack('<3d', *vertex.co))
    for face in mesh.polygons:
        digest.update(struct.pack('<2I', face.material_index, len(face.vertices)))
        digest.update(struct.pack('<' + 'I' * len(face.vertices), *face.vertices))
    digest.update(json.dumps([m.name if m else None for m in mesh.materials]).encode())
    return digest.hexdigest()


def _collect(
    geometry_policy: dict | None = None, mesh_dir: Path | None = None, *, texture_capture=None,
    image_surfaces=False,
) -> tuple[dict, dict]:
    scene = bpy.context.scene
    scale = scene.unit_settings.scale_length
    if not math.isfinite(scale) or scale <= 0:
        raise WorkerFailure(
            "not_measurable",
            "INVALID_SCENE_SCALE",
            "Scene scale must be positive and finite",
        )
    render_names = set()

    def prepare(layer):
        if layer.exclude or layer.collection.hide_render:
            return
        layer.hide_viewport = False
        layer.collection.hide_viewport = False
        render_names.update(
            obj.name for obj in layer.collection.objects if not obj.hide_render
        )
        for child in layer.children:
            prepare(child)

    prepare(bpy.context.view_layer.layer_collection)
    for obj in scene.objects:
        if obj.name in render_names:
            obj.hide_set(False)
            obj.hide_viewport = False
        for modifier in obj.modifiers:
            modifier.show_viewport = modifier.show_render
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects, trees, all_points = {}, {}, []
    converted_surfaces = {}
    surface_types = {'CURVE', 'SURFACE', 'FONT'} if image_surfaces else set()
    material_audit = _procedural_materials().MaterialAudit()
    for obj in scene.objects:
        is_surface = obj.type in surface_types
        measured_type = 'MESH' if is_surface else obj.type
        facts = {
            "type": measured_type,
            **({'source_type': obj.type, 'geometry_conversion': 'evaluated_to_mesh_without_scene_edit'} if is_surface else {}),
            "parent": obj.parent.name if obj.parent else None,
            "visible_render": obj.name in render_names,
            "location": [float(v * scale) for v in obj.matrix_world.translation],
            "matrix_world": [list(row) for row in obj.matrix_world],
            "modifiers": [m.type for m in obj.modifiers],
            "original_hide_render": bool(obj.hide_render),
            "entity_scope": "delivery_geometry"
            if obj.name in render_names and measured_type == "MESH"
            else "unsupported_delivery_geometry"
            if obj.name in render_names and obj.type not in _NON_GEOMETRIC_TYPES
            else "hidden_geometry"
            if obj.type not in _NON_GEOMETRIC_TYPES
            else "non_geometric_helper",
        }
        objects[obj.name] = facts
        if measured_type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        if mesh is None:
            raise WorkerFailure('not_measurable', 'SURFACE_CONVERSION_UNAVAILABLE', obj.name)
        validator_spec = importlib.util.spec_from_file_location(
            '_l1_mesh_indices', Path(__file__).with_name('l1_mesh_indices.py'))
        validator = importlib.util.module_from_spec(validator_spec)
        validator_spec.loader.exec_module(validator)
        invalid = validator.invalid_reference(mesh)
        if invalid is not None:
            evaluated.to_mesh_clear()
            raise WorkerFailure('not_measurable', 'INVALID_MESH_INDICES',
                                json.dumps(dict(object=obj.name, invalid=invalid)))
        if is_surface:
            converted_surfaces[obj.name] = _surface_mesh_signature(mesh)
        # Object-linked overrides are effective shading inputs but are NOT
        # reflected by evaluated.to_mesh().materials (confirmed in Blender).
        effective_materials = [
            evaluated.material_slots[index].material
            if index < len(evaluated.material_slots) and evaluated.material_slots[index].link == "OBJECT"
            else material for index, material in enumerate(mesh.materials)
        ]
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            if obj.name in render_names:
                override = bpy.context.view_layer.material_override
                material_audit.materials(
                    [override] if override else effective_materials,
                    {0} if override and bm.faces else {face.material_index for face in bm.faces},
                    f"object:{obj.name}",
                )
            bm.transform(evaluated.matrix_world)
            mirrored = evaluated.matrix_world.determinant() < 0
            if geometry_policy and mirrored:
                bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
            for vertex in bm.verts:
                vertex.co *= scale
            facts["raw_vertices"] = len(bm.verts)
            facts["raw_faces"] = len(bm.faces)
            facts["raw_degenerate_faces"] = sum(
                _face_area(f) <= 1e-18 for f in bm.faces
            )
            facts["raw_nonmanifold_edges"] = sum(
                not edge.is_manifold for edge in bm.edges
            )
            # glTF can duplicate positions at UV/normal seams. Topology is
            # measured on a welded copy with a frozen one-nanometre tolerance.
            weld = geometry_policy["weld_m"] if geometry_policy else 1e-9
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=weld)
            bm.normal_update()
            points = [v.co.copy() for v in bm.verts]
            if any(not math.isfinite(v) for point in points for v in point):
                raise WorkerFailure(
                    "not_measurable",
                    "NONFINITE_GEOMETRY",
                    f"Non-finite geometry: {obj.name}",
                )
            bounds, dimensions = _bounds(points)
            nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
            nonmanifold_vertices = sum(not vertex.is_manifold for vertex in bm.verts)
            degenerate = sum(_face_area(face) <= 1e-18 for face in bm.faces)
            signed_volume = float(bm.calc_volume(signed=True)) if bm.faces else 0.0
            volume = abs(signed_volume)
            closed = bool(bm.faces) and nonmanifold == 0 and degenerate == 0
            if geometry_policy:
                closed = closed and nonmanifold_vertices == 0
            first_face = next(
                (face for face in bm.faces if _face_area(face) > 1e-18), None
            )
            nonplanar = bool(first_face) and any(
                abs((point - first_face.verts[0].co).dot(first_face.normal)) > 1e-8
                for point in points
            )
            facts.update(
                {
                    "vertices": len(bm.verts),
                    "edges": len(bm.edges),
                    "faces": len(bm.faces),
                    "bounds": bounds,
                    "dimensions": dimensions,
                    "volume": volume,
                    "components": _components(bm),
                    "nonmanifold_edges": nonmanifold,
                    "nonmanifold_vertices": nonmanifold_vertices,
                    "degenerate_faces": degenerate,
                    "inconsistent_edges": sum(
                        e.is_manifold and not e.is_contiguous for e in bm.edges
                    ),
                    "closed": closed,
                    "nonplanar": nonplanar,
                    "material_colors": [
                        list(mat.diffuse_color) for mat in effective_materials if mat
                    ],
                    "material_color_evidence": _material_color_evidence(effective_materials),
                    "material_surface": _material_probe().capture_materials(effective_materials),
                    "material_slot_source": "evaluated_mesh_with_object_overrides",
                    "editable": obj.library is None and obj.data.library is None,
                    "signed_volume_integral_m3": signed_volume,
                    "topology_weld_m": weld,
                    "welded_vertices": facts["raw_vertices"] - len(bm.verts),
                    "removed_faces_after_weld": facts["raw_faces"] - len(bm.faces),
                    "mirror_winding_corrected": bool(geometry_policy and mirrored),
                    "volume_reliable": False,
                    "solid_volume_m3": None,
                }
            )
            if geometry_policy and facts["visible_render"]:
                if texture_capture is not None:
                    facts['material_textures'] = texture_capture.materials(effective_materials, {face.material_index for face in bm.faces})
                    facts['default_render_uv_layer'] = next((layer.name for layer in mesh.uv_layers if layer.active_render), None)
                    facts['material_fields'] = _shader_fields().capture_material_fields(
                        effective_materials, capture=texture_capture, default_uv=facts['default_render_uv_layer'],
                        uv_layers=list(mesh.uv_layers.keys()), used_slots={face.material_index for face in bm.faces},
                    )
                    facts['material_compiled_fields'] = _principled_fields().capture_principled_fields(
                        effective_materials, capture=texture_capture, default_uv=facts['default_render_uv_layer'],
                        uv_layers=list(mesh.uv_layers.keys()), used_slots={face.material_index for face in bm.faces},
                    )
                payload_path = (
                    mesh_dir / f"entity-{len(objects):05d}.npz" if mesh_dir else None
                )
                _solid_audit(bm, facts, geometry_policy, payload_path)
                # Preserve the raw integral under an explicit name. The plain
                # volume in the new policy is only a validated solid volume.
                facts["volume_integral_absolute_m3"] = abs(
                    facts["signed_volume_integral_m3"]
                )
                facts["volume"] = facts["solid_volume_m3"]
            elif geometry_policy:
                facts["volume_integral_absolute_m3"] = volume
                facts["volume"] = None
                facts["audit_status"] = "hidden_auxiliary_not_a_delivery_solid"
            if bm.faces:
                trees[obj.name] = BVHTree.FromBMesh(bm)
            if facts["visible_render"]:
                all_points.extend(points)
        finally:
            bm.free()
            evaluated.to_mesh_clear()
    mesh_names = [
        name
        for name, obj in objects.items()
        if obj["type"] == "MESH" and obj["visible_render"]
    ]
    hierarchy_roots: dict[str, str | None] = {}
    hierarchy_cycles: list[str] = []
    for name in mesh_names:
        current = name
        seen: set[str] = set()
        while current in objects and objects[current].get("parent") is not None:
            if current in seen:
                hierarchy_cycles.append(name)
                hierarchy_roots[name] = None
                break
            seen.add(current)
            parent = objects[current].get("parent")
            if not isinstance(parent, str):
                hierarchy_roots[name] = None
                break
            current = parent
        else:
            hierarchy_roots[name] = current if current in objects else None
    root_names = sorted(
        {root for root in hierarchy_roots.values() if root is not None}
    )
    hierarchy = {
        "common_root": bool(mesh_names)
        and not hierarchy_cycles
        and len(root_names) == 1
        and all(root is not None for root in hierarchy_roots.values()),
        "root_names": root_names,
        "roots_by_mesh": hierarchy_roots,
        "cycles": sorted(set(hierarchy_cycles)),
        "delivery_mesh_count": len(mesh_names),
    }
    bounds, dimensions = _bounds(all_points)
    unsupported = [
        name
        for name, item in objects.items()
        if item["entity_scope"] == "unsupported_delivery_geometry"
    ]
    instance_census = []
    for instance in depsgraph.object_instances:
        if not instance.is_instance:
            continue
        owner = (
            instance.parent.original.name
            if instance.parent
            else instance.object.original.name
        )
        # Blender 5.2 exposes the evaluated mesh of an ordinary curve as a
        # self-instance. Count it once only when source, pose and exact mesh
        # match the surface already measured above. Genuine instances remain
        # an explicit limit; this does not silently ignore duplicated objects.
        surface_alias = False
        original = instance.object.original
        if (image_surfaces and owner == original.name and owner in converted_surfaces
                and instance.object.type == 'MESH'
                and all(abs(instance.matrix_world[i][j] - original.matrix_world[i][j]) < 1e-9
                        for i in range(4) for j in range(4))):
            instance_mesh = instance.object.to_mesh()
            try:
                surface_alias = (instance_mesh is not None and
                    _surface_mesh_signature(instance_mesh) == converted_surfaces[owner])
            finally:
                instance.object.to_mesh_clear()
        instance_census.append(
            {
                "owner": owner,
                "source": instance.object.original.name,
                "source_type": instance.object.type,
                "visible_owner": owner in render_names,
                **({'evaluated_surface_alias': surface_alias} if image_surfaces else {}),
                "matrix_world": [list(row) for row in instance.matrix_world],
            }
        )
    instances = any(item["visible_owner"] and not item.get('evaluated_surface_alias') for item in instance_census)
    primary = None
    if len(mesh_names) == 1:
        # A task may require one editable entity without prescribing its
        # object name. Expose the sole evaluated mesh through a semantic alias
        # for pose/material checks; the original object table remains intact
        # for diagnostics and provenance.
        primary = objects[mesh_names[0]]
    material_audit.scene(scene, render_names, bpy.context.view_layer)
    return {
        "blender_version": bpy.app.version_string,
        "procedural_materials": material_audit.result(frame=scene.frame_current),
        "unit_scale": scale,
        "coordinate_units": "metres",
        "objects": objects,
        "mesh_count": len(mesh_names),
        "object_count": len(objects),
        "bounds": bounds,
        "dimensions": dimensions,
        "max_span_m": max(dimensions) if dimensions else None,
        # Collected before evaluator cameras/render overrides. These are facts
        # about the saved scene, not proof that its submitted PNG came from it.
        "render_settings": {
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "resolution_percentage": scene.render.resolution_percentage,
            "effective_resolution": [
                scene.render.resolution_x * scene.render.resolution_percentage // 100,
                scene.render.resolution_y * scene.render.resolution_percentage // 100,
            ],
            "view_transform": scene.view_settings.view_transform,
            "exposure": float(scene.view_settings.exposure),
            "has_camera": scene.camera is not None,
            "camera_name": scene.camera.name if scene.camera else None,
            "visible_light_count": sum(
                obj.type == 'LIGHT' and obj.name in render_names for obj in scene.objects
            ),
        },
        "all_closed": bool(mesh_names)
        and all(objects[name]["closed"] for name in mesh_names),
        "all_connected": bool(mesh_names)
        and all(objects[name]["components"] == 1 for name in mesh_names),
        "all_editable": bool(mesh_names)
        and all(objects[name]["editable"] for name in mesh_names),
        "all_parented": bool(mesh_names)
        and all(objects[name]["parent"] is not None for name in mesh_names),
        "has_real_geometry": any(
            objects[name]["faces"] > 0 and objects[name]["nonplanar"]
            for name in mesh_names
        ),
        "unsupported_geometry": unsupported,
        "has_instances": instances,
        "instance_census": instance_census,
        "primary": primary,
        "geometry_policy": geometry_policy,
        "entity_scope_policy": {
            "delivery": "render-enabled evaluated meshes in the active view layer; names are not selectors",
            "hidden": "inventoried auxiliary geometry, not counted as delivered parts",
            "helpers": "cameras/lights/empties and other non-geometric objects never satisfy a part",
            "modifiers": "evaluated with viewport visibility set to render visibility",
            "unsupported": ("metaballs/volumes/pointclouds and genuine instances remain explicit tool limits; curves/surfaces/text use evaluated meshes"
                if image_surfaces else "render-visible curves/surfaces/text/metaballs/volumes/pointclouds and instances are explicit tool limits"),
        },
        "hierarchy": hierarchy,
        "entity_census": {
            scope: sorted(
                name for name, item in objects.items() if item["entity_scope"] == scope
            )
            for scope in (
                "delivery_geometry",
                "hidden_geometry",
                "non_geometric_helper",
                "unsupported_delivery_geometry",
            )
        },
        "all_valid_solids": bool(geometry_policy and mesh_names)
        and all(objects[n].get("valid_solid") for n in mesh_names),
        "all_volume_reliable": bool(geometry_policy and mesh_names)
        and all(objects[n].get("volume_reliable") for n in mesh_names),
    }, trees


def _inside(tree: BVHTree, point: list[float]) -> bool:
    """Parity rays in three frozen directions; boundary probes must be avoided."""
    votes = []
    for direction in ((1, 0.371, 0.127), (0.193, 1, 0.417), (0.239, 0.173, 1)):
        ray = Vector(direction).normalized()
        origin = Vector(point)
        intersections = 0
        for _ in range(10000):
            hit, _, _, _ = tree.ray_cast(origin, ray)
            if hit is None:
                break
            intersections += 1
            # mathutils stores float32 coordinates: a fixed tiny offset can
            # round back onto the same triangle for metre-scale objects.
            epsilon = max(1e-8, hit.length * 1e-6)
            origin = hit + ray * epsilon
        else:
            raise RuntimeError("Occupancy ray exceeded intersection budget")
        votes.append(bool(intersections % 2))
    return sum(votes) >= 2


def _ray_distance(
    trees: list[BVHTree], origin: Vector, direction: Vector
) -> float | None:
    """Return the nearest surface distance along a radial section ray."""
    nearest: float | None = None
    direction = direction.normalized()
    for tree in trees:
        hit, _, _, _ = tree.ray_cast(origin, direction)
        if hit is None:
            continue
        distance = float((hit - origin).length)
        if distance <= 1e-8:
            continue
        if nearest is None or distance < nearest:
            nearest = distance
    return nearest


def _feature_objects(params: dict, facts: dict, spec: dict | None = None) -> list[str]:
    """Select a feature-bearing mesh by explicit name or dimension signature."""
    if "objects" in params:
        return [
            name
            for name in params["objects"]
            if name in facts["objects"]
            and facts["objects"][name].get("type") == "MESH"
            and facts["objects"][name].get("visible_render", True)
        ]
    expected = params.get("object_dimensions")
    if not isinstance(expected, list) or len(expected) != 3:
        return []
    tolerance = params.get("object_dimension_tolerance", 1e-6)
    if isinstance(tolerance, str) and isinstance(spec, dict):
        tolerance = spec.get("tolerances", {}).get(tolerance)
    try:
        tolerance = float(tolerance)
        target = sorted(float(value) for value in expected)
    except (TypeError, ValueError):
        return []
    if not math.isfinite(tolerance) or tolerance < 0:
        return []
    selected = []
    for name, item in facts["objects"].items():
        if item.get("type") != "MESH" or not item.get("visible_render", True):
            continue
        dimensions = item.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) != 3:
            continue
        try:
            measured = sorted(float(value) for value in dimensions)
        except (TypeError, ValueError):
            continue
        if all(abs(left - right) <= tolerance for left, right in zip(measured, target)):
            selected.append(name)
    return sorted(selected)


def _hole_patterns(spec: dict, facts: dict, trees: dict) -> dict:
    """Measure a set of plate holes, including an axial open-corridor check."""
    results: dict[str, dict | None] = {}
    for checks in spec["checks"].values():
        for check in checks:
            if check["metric"] != "hole_pattern" or not check.get("applicable", True):
                continue
            params = check["params"]
            names = _feature_objects(params, facts, spec)
            centers = params.get("centers", [])
            selected = [trees[name] for name in names if name in trees]
            if len(names) != 1 or len(selected) != 1 or not isinstance(centers, list):
                results[check["id"]] = None
                continue
            name = names[0]
            bounds = facts["objects"][name].get("bounds")
            if not isinstance(bounds, list) or len(bounds) != 2:
                results[check["id"]] = None
                continue
            relative_to_object = params.get("relative_to_object", False)
            # The plan center is a geometric datum, not the arbitrary Blender
            # origin. Moving an origin without changing the mesh is legal.
            plan_center = [(bounds[0][i] + bounds[1][i]) / 2 for i in (0, 1)]
            expected_radius = float(params["radius"])
            tolerance_value = params["tolerance"]
            if isinstance(tolerance_value, str):
                tolerance_value = spec.get("tolerances", {}).get(tolerance_value)
            tolerance = float(tolerance_value)
            z_values = [float(value) for value in params["z_values"]]
            angular_samples = int(params.get("angular_samples", 32))
            axis_samples = int(params.get("axis_samples", 9))
            hole_rows = []
            for center_xy in centers:
                if not isinstance(center_xy, list) or len(center_xy) != 2:
                    hole_rows.append({"center": center_xy, "valid": False})
                    continue
                center = Vector((float(center_xy[0]), float(center_xy[1]), 0.0))
                if relative_to_object:
                    center.x += float(plan_center[0])
                    center.y += float(plan_center[1])
                radii_by_layer = []
                for z in z_values:
                    world_z = float(z)
                    if relative_to_object:
                        world_z += float(bounds[0][2])
                    origin = Vector((center.x, center.y, world_z))
                    radii = []
                    for index in range(angular_samples):
                        angle = 2.0 * math.pi * index / angular_samples
                        direction = Vector((math.cos(angle), math.sin(angle), 0.0))
                        distance = _ray_distance(selected, origin, direction)
                        if distance is not None:
                            radii.append(distance)
                    radii_by_layer.append(
                        {
                            "z": world_z,
                            "local_z": float(z),
                            "radius": float(sorted(radii)[len(radii) // 2])
                            if radii
                            else None,
                            "samples": len(radii),
                        }
                    )
                axis_blocked = False
                axis_checks = []
                for index in range(1, max(2, axis_samples - 1)):
                    fraction = index / max(1, axis_samples - 1)
                    point = [
                        float(center.x),
                        float(center.y),
                        float(bounds[0][2] + (bounds[1][2] - bounds[0][2]) * fraction),
                    ]
                    inside = _inside(selected[0], point)
                    axis_checks.append({"point": point, "inside": inside})
                    axis_blocked = axis_blocked or inside
                measured_radii = [
                    row["radius"] for row in radii_by_layer if row["radius"] is not None
                ]
                complete = len(measured_radii) == len(radii_by_layer) and bool(measured_radii)
                max_error = (
                    max(abs(radius - expected_radius) for radius in measured_radii)
                    if measured_radii
                    else None
                )
                hole_rows.append(
                    {
                        "center": list(center_xy),
                        "world_center": [float(center.x), float(center.y)],
                        "layers": radii_by_layer,
                        "max_radius_error": max_error,
                        "through_axis": complete and not axis_blocked,
                        "axis_checks": axis_checks,
                        "within_tolerance": complete
                        and max_error is not None
                        and max_error <= tolerance
                        and not axis_blocked,
                    }
                )
            results[check["id"]] = {
                "object": name,
                "coordinate_mode": "plate_bounds_relative" if relative_to_object else "world",
                "expected_radius": expected_radius,
                "tolerance": tolerance,
                "holes": hole_rows,
                "expected_count": len(centers),
                "measured_count": len(hole_rows),
                "within_tolerance": bool(hole_rows)
                and len(hole_rows) == len(centers)
                and all(row.get("within_tolerance") is True for row in hole_rows),
            }
    return results


def _hole_profiles(spec: dict, facts: dict, trees: dict) -> dict:
    """Measure circular hole radii at several z sections.

    A radial ray starts in the declared hole centre and records the first
    evaluated mesh surface. For a genuine through-hole this is the inner wall;
    a solid centre instead reports the outer surface and fails the radius
    tolerance. Multiple z sections prevent a thin capped pocket from passing
    as a hole.
    """
    results: dict[str, dict] = {}
    for checks in spec["checks"].values():
        for check in checks:
            if check["metric"] != "hole_profile" or not check.get("applicable", True):
                continue
            params = check["params"]
            names = params.get(
                "objects",
                [
                    name
                    for name, item in facts["objects"].items()
                    if item.get("type") == "MESH" and item.get("visible_render", True)
                ],
            )
            selected = [trees[name] for name in names if name in trees]
            if facts.get("geometry_policy") and any(
                not facts["objects"].get(name, {}).get("volume_reliable")
                for name in names
            ):
                results[check["id"]] = None
                continue
            if not selected:
                results[check["id"]] = None
                continue
            center_xy = params["center"]
            center = Vector((center_xy[0], center_xy[1], 0.0))
            radii_by_layer: list[dict] = []
            samples = int(params.get("angular_samples", 32))
            for z in params["z_values"]:
                origin = Vector((center.x, center.y, z))
                radii = []
                for index in range(samples):
                    angle = 2.0 * math.pi * index / samples
                    direction = Vector((math.cos(angle), math.sin(angle), 0.0))
                    distance = _ray_distance(selected, origin, direction)
                    if distance is not None:
                        radii.append(distance)
                if not radii:
                    radii_by_layer.append({"z": z, "radius": None, "samples": 0})
                    continue
                radii_by_layer.append(
                    {
                        "z": z,
                        "radius": float(sorted(radii)[len(radii) // 2]),
                        "min_radius": float(min(radii)),
                        "max_radius": float(max(radii)),
                        "samples": len(radii),
                    }
                )
            expected = float(params["radius"])
            tolerance_value = params["tolerance"]
            if isinstance(tolerance_value, str):
                tolerance_value = spec.get("tolerances", {}).get(tolerance_value)
            tolerance = float(tolerance_value)
            errors = [
                abs(layer["radius"] - expected)
                for layer in radii_by_layer
                if layer["radius"] is not None
            ]
            all_layers = len(errors) == len(radii_by_layer) and bool(errors)
            results[check["id"]] = {
                "center": list(center),
                "expected_radius": expected,
                "tolerance": tolerance,
                "layers": radii_by_layer,
                "max_radius_error": max(errors) if errors else None,
                "through_layers": all_layers,
            }
    return results


def _probes(spec: dict, facts: dict, trees: dict) -> dict:
    results = {}
    for checks in spec["checks"].values():
        for check in checks:
            if check["metric"] != "occupancy" or not check.get("applicable", True):
                continue
            params = check["params"]
            names = params.get(
                "objects",
                [name for name in trees if facts["objects"][name]["visible_render"]],
            )
            if not names or any(
                name not in trees
                or not facts["objects"][name]["closed"]
                or (
                    facts.get("geometry_policy")
                    and not facts["objects"][name].get("volume_reliable")
                )
                for name in names
            ):
                results[check["id"]] = None
                continue
            results[check["id"]] = [
                any(_inside(trees[name], point) for name in names)
                for point in params["points"]
            ]
    results.update(_hole_profiles(spec, facts, trees))
    results.update(_hole_patterns(spec, facts, trees))
    return results


def _save_mask(path: Path, size: int, pixels: bytearray) -> None:
    """Write an exact 8-bit grayscale PNG without color management or Pillow."""

    def chunk(kind: bytes, content: bytes) -> bytes:
        return (
            struct.pack("!I", len(content))
            + kind
            + content
            + struct.pack("!I", zlib.crc32(kind + content) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\x00" + pixels[y * size : (y + 1) * size] for y in range(size))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", size, size, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _native_beauty_render(view: dict, output_dir: Path) -> dict:
    """Render the submitted shaders/lights with an evaluator-owned camera.

    Keep the scene's engine and appearance, including Workbench studio settings
    when that is the authored engine. Never replace shaders, lights or world
    with a proxy renderer. This worker is disposable and never saves the blend.
    """
    if view.get('camera_source') in {'saved', 'declared'}:
        module_spec = importlib.util.spec_from_file_location(
            'l1_image_blender', Path(__file__).with_name('l1_image_blender.py'))
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        try:
            renderer = module.render_saved if view['camera_source'] == 'saved' else module.render_declared
            return renderer(view, output_dir)
        except ValueError as error:
            raise WorkerFailure('not_measurable', 'SAVED_RENDER_UNSUPPORTED', str(error)) from error
    scene = bpy.context.scene
    scene.frame_set(view.get("frame", 1))
    scale = scene.unit_settings.scale_length
    width, height = view.get("beauty_resolution", [960, 720])
    camera_data = bpy.data.cameras.new("__l1_eval_camera")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = view["ortho_scale"] / scale
    camera_data.clip_start = 1e-5 / scale
    camera_data.clip_end = 1000.0 / scale
    camera = bpy.data.objects.new(camera_data.name, camera_data)
    scene.collection.objects.link(camera)
    camera.location = Vector(view["location"]) / scale
    direction = Vector(view["target"]) / scale - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    # A camera bound to an animation marker must not override our frozen view.
    for marker in scene.timeline_markers:
        marker.camera = None
    scene.camera = camera
    render = scene.render
    render.resolution_x, render.resolution_y = width, height
    render.resolution_percentage = 100
    render.pixel_aspect_x = render.pixel_aspect_y = 1
    render.use_border = False
    render.use_crop_to_border = False
    render.film_transparent = False
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGBA"
    render.image_settings.color_depth = "8"
    render.use_file_extension = True
    render.use_compositing = False
    render.use_sequencer = False
    if hasattr(render, "use_multiview"):
        render.use_multiview = False
    engine = render.engine
    if engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 32
        scene.cycles.seed = 0
        scene.cycles.use_animated_seed = False
        scene.cycles.use_adaptive_sampling = False
        scene.cycles.use_denoising = False
    path = output_dir / f"{view['id']}_beauty.png"
    render.filepath = str(path)
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    if not path.is_file():
        raise RuntimeError("Blender did not write the requested beauty image")
    return {
        "image": str(path),
        "frame": view.get("frame", 1),
        "beauty_backend": "blender_native",
        "engine": engine,
        "render_protocol": "l1-native-appearance-v1",
        "resolution": [width, height],
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": scene.view_settings.exposure,
        "gamma": scene.view_settings.gamma,
        "scene_light_count": sum(o.type == "LIGHT" for o in scene.objects),
        "lighting_mode": "workbench_studio"
        if engine == "BLENDER_WORKBENCH"
        else "scene",
        "cycles_samples": 32 if engine == "CYCLES" else None,
    }


def _silhouettes(spec: dict, output_dir: Path) -> dict:
    views = {}
    scene = bpy.context.scene
    for view in spec.get("render_views", []):
        scene.frame_set(view.get("frame", 1))
        facts, trees = _collect(image_surfaces='l1_image_quality' in spec)
        visible_trees = {
            name: tree
            for name, tree in trees.items()
            if facts["objects"][name]["visible_render"]
        }
        size = view.get("resolution", 256)
        location = Vector(view["location"])
        direction = (Vector(view["target"]) - location).normalized()
        rotation = direction.to_track_quat("-Z", "Y")
        right, up = rotation @ Vector((1, 0, 0)), rotation @ Vector((0, 1, 0))
        pixels = bytearray(size * size)
        step = view["ortho_scale"] / size
        for y in range(size):
            row_origin = location + up * ((size / 2 - y - 0.5) * step)
            for x in range(size):
                origin = row_origin + right * ((x + 0.5 - size / 2) * step)
                if any(
                    tree.ray_cast(origin, direction)[0] is not None
                    for tree in visible_trees.values()
                ):
                    pixels[y * size + x] = 255
        mask = output_dir / f"{view['id']}.png"
        _save_mask(mask, size, pixels)
        entry = {"mask": str(mask), "frame": view.get("frame", 1)}
        views[view["id"]] = entry
    return views


def _collect_state(args, spec, directory: Path) -> dict:
    """Collect a frame without reopening the scene or changing its frame."""
    directory.mkdir(parents=True, exist_ok=True)
    geometry_policy = spec.get("l1_geometry")
    if geometry_policy:
        _mesh_kernel().validate_geometry_policy(geometry_policy)
    visual_only = spec.get('l1_image_quality', {}).get('version') == 'l1-reference-visual-v2.0.0'
    if visual_only:
        # Visual v2 does not measure CAD equivalence or solid topology. Running
        # that audit here can discard otherwise loadable, renderable scenes at
        # its 200k-triangle limit before the actual visual checks are collected.
        # Basic real-geometry and material-dependency checks still run below.
        geometry_policy = None
    resource_roots = tuple(getattr(args, 'material_resource_root', ()))
    textures = _texture_probe().TextureCapture(directory / 'textures', resource_roots=resource_roots) if geometry_policy else None
    facts, trees = _collect(geometry_policy, directory / "meshes" if geometry_policy else None,
        texture_capture=textures, image_surfaces='l1_image_quality' in spec)
    if geometry_policy:
        facts['texture_resource_policy'] = {'protocol': 'l1-texture-resource-policy-v1',
                                            'external_roots': [str(Path(root).resolve()) for root in resource_roots],
                                            'default_external_access': 'denied', 'packed_images': 'allowed'}
    if facts["unsupported_geometry"] or facts["has_instances"]:
        (directory / "partial_facts.json").write_text(
            json.dumps({"scene": facts}, ensure_ascii=False, allow_nan=False), encoding="utf-8",
        )
        raise WorkerFailure(
            "not_implemented", "UNSUPPORTED_GEOMETRY",
            "Inspector currently requires meshes with instances realized; "
            f"unsupported={facts['unsupported_geometry']}, instances={facts['has_instances']}",
        )
    if visual_only:
        facts['geometry_collection_scope'] = 'visual_delivery_only_no_cad_solid_audit'
    return {"scene": facts, "probes": {} if visual_only else _probes(spec, facts, trees), "views": {}}


def _inspect_state_sequence(args, spec, source_hash: str, spec_hash: str) -> dict:
    """Observe requested frames in the one already-opened, autoexec-disabled file.

    This is evidence collection, not a shape-preservation or separation verdict.
    Blender session identities are local to this process, not cross-file roles.
    """
    sequence = {
        "protocol": "l1-state-sequence-v1", "status": "running",
        "session_id": uuid.uuid4().hex, "process_id": os.getpid(), "file_loads": 1,
        "scene_path": str(args.scene.resolve()), "scene_sha256": source_hash,
        "spec_sha256": spec_hash, "frames": args.frames, "snapshots": [],
        "autoexec_enabled": False, "identity_kind": "blender_id_session_uid",
        "collection_mode": "evaluated_render_geometry",
        "limitations": ["Collection alone does not establish restoration, rigid shape preservation or separation",
                        "Native node materials and face assignments are not fully compared",
                        "Candidate Python handlers and drivers requiring autoexec are not enabled"],
    }
    partial = args.output.parent / "state_sequence.partial.json"

    def checkpoint():
        partial.write_text(json.dumps(sequence, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")

    checkpoint()
    for index, frame in enumerate(args.frames):
        bpy.context.scene.frame_set(frame)
        facts = _collect_state(args, spec, args.output.parent / f"state-{index:02d}")
        for name, item in facts["scene"]["objects"].items():
            identity = getattr(bpy.context.scene.objects[name], "session_uid", None)
            if type(identity) is not int or identity <= 0:
                raise WorkerFailure("not_implemented", "SESSION_IDENTITY_UNAVAILABLE", "Stable Blender object session identity is unavailable")
            item["session_identity"] = identity
        sequence["snapshots"].append({"index": index, "frame": frame,
                                      "observed_frame": bpy.context.scene.frame_current, **facts})
        checkpoint()
    if hashlib.sha256(args.scene.read_bytes()).hexdigest() != source_hash or hashlib.sha256(args.spec.read_bytes()).hexdigest() != spec_hash:
        raise WorkerFailure("not_measurable", "INSPECTION_INPUT_CHANGED", "Scene or specification changed during sequence inspection")
    sequence["status"] = "completed"
    checkpoint()
    # Preserve the familiar top-level scene for existing evidence consumers;
    # each snapshot owns its separate mesh files, including the repeated frame.
    return {"scene": sequence["snapshots"][0]["scene"], "views": {}, "state_sequence": sequence}


def _run(args) -> None:
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False
    if args.frames is not None and (
        not args.frames or len(args.frames) > 16 or any(frame < 0 for frame in args.frames)
        or args.scene.suffix.lower() != ".blend" or not args.no_views or args.beauty_view
    ):
        raise WorkerFailure("not_measurable", "INVALID_STATE_SEQUENCE", "Sequence inspection requires 1–16 nonnegative native frames, no views or beauty render")
    source_hash = hashlib.sha256(args.scene.read_bytes()).hexdigest() if args.frames is not None else None
    spec_hash = hashlib.sha256(args.spec.read_bytes()).hexdigest() if args.frames is not None else None
    try:
        if args.scene.suffix.lower() == ".blend":
            bpy.ops.wm.open_mainfile(
                filepath=str(args.scene), load_ui=False, use_scripts=False
            )
        elif args.scene.suffix.lower() in {".glb", ".gltf"}:
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=str(args.scene))
        else:
            raise WorkerFailure(
                "not_implemented", "UNSUPPORTED_SCENE_FORMAT", str(args.scene.suffix)
            )
    except (RuntimeError, ValueError, OSError) as error:
        if isinstance(error, WorkerFailure):
            raise
        raise WorkerFailure(
            "not_measurable", "CANDIDATE_LOAD_ERROR", str(error)
        ) from error
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.frames is not None:
        result = _inspect_state_sequence(args, spec, source_hash, spec_hash)
        args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        return
    if args.beauty_view:
        view = next(v for v in spec["render_views"] if v["id"] == args.beauty_view)
        result = {
            "views": {view["id"]: _native_beauty_render(view, args.output.parent)}
        }
        args.output.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        return
    if args.frame < 0:
        raise WorkerFailure("not_measurable", "INVALID_FRAME", "Frame must be nonnegative")
    bpy.context.scene.frame_set(args.frame)
    result = _collect_state(args, spec, args.output.parent)
    if not args.no_views:
        result["views"] = _silhouettes(spec, args.output.parent)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-views", action="store_true")
    parser.add_argument("--beauty-view")
    parser.add_argument("--frame", type=int, default=1)
    parser.add_argument("--frames", nargs="+", type=int)
    parser.add_argument('--material-resource-root', type=Path, action='append', default=[])
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        _run(args)
    except Exception as error:  # Classify unexpected exceptions at the worker boundary.
        failure = (
            error
            if isinstance(error, WorkerFailure)
            else WorkerFailure(
                "infrastructure_error",
                "WORKER_INTERNAL_ERROR",
                f"{type(error).__name__}: {error}",
            )
        )
        (args.output.parent / "failure.json").write_text(
            json.dumps(
                {
                    "status": failure.status,
                    "code": failure.code,
                    "reason": failure.reason[:16000],
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        raise


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - dedicated worker must report all failures
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    else:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
