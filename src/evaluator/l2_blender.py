"""Blender-side L2 evidence collector.

The worker opens a submission-owned scene with auto-execution disabled and
extracts evaluator-owned facts from evaluated geometry. Candidate annotations,
authored cameras and submitted score files are never used as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def _components(bm: bmesh.types.BMesh) -> int:
    remaining = set(bm.verts)
    count = 0
    while remaining:
        stack = [remaining.pop()]
        count += 1
        while stack:
            for edge in stack.pop().link_edges:
                for vertex in edge.verts:
                    if vertex in remaining:
                        remaining.remove(vertex)
                        stack.append(vertex)
    return count


def _bounds(points: list[Vector]) -> list[list[float]] | None:
    if not points:
        return None
    low = [min(point[i] for point in points) for i in range(3)]
    high = [max(point[i] for point in points) for i in range(3)]
    return [low, high]


def _materials(mesh: bpy.types.Mesh) -> tuple[list[str], int]:
    names = []
    image_textures = 0
    for material in mesh.materials:
        if material is None:
            continue
        names.append(material.name)
        if material.use_nodes:
            image_textures += sum(
                node.type == "TEX_IMAGE" for node in material.node_tree.nodes
            )
    return names, image_textures


def _role_owner(obj):
    """Repeated same-role tags describe one explicit ancestor entity.

    An intervening different role is an entity boundary; unrelated objects or
    siblings are never merged merely because they share a role or a name.
    """
    owner = obj
    while owner.parent is not None and not owner.get("bench_role"):
        owner = owner.parent
    role = owner.get("bench_role")
    if isinstance(role, str) and role:
        parent = owner.parent
        while parent is not None:
            claim = parent.get("bench_role")
            if claim:
                if claim != role:
                    break
                owner = parent
            parent = parent.parent
    return owner


def _object_facts(obj: bpy.types.Object, depsgraph, scale: float) -> dict:
    owner = _role_owner(obj)
    role = owner.get("bench_role")
    part = obj.get("bench_part")
    result = {
        "role": role if isinstance(role, str) else None,
        "entity": owner.name,
        "declared_role": obj.get("bench_role") if isinstance(obj.get("bench_role"), str) else None,
        "part": part if isinstance(part, str) else None,
        "type": obj.type,
        "parent": obj.parent.name if obj.parent else None,
        "location": [float(value * scale) for value in obj.matrix_world.translation],
        "rotation": [float(value) for value in obj.matrix_world.to_euler()],
        "scale": [float(value) for value in obj.scale],
        "visible_render": not obj.hide_render and any(not c.hide_render for c in obj.users_collection),
        "editable": obj.library is None and getattr(obj.data, "library", None) is None,
        "modifiers": [modifier.type for modifier in obj.modifiers],
    }
    if obj.type != "MESH":
        return result
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.transform(evaluated.matrix_world)
        for vertex in bm.verts:
            vertex.co *= scale
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-9)
        bm.normal_update()
        points = [vertex.co.copy() for vertex in bm.verts]
        bounds = _bounds(points)
        dimensions = [bounds[1][i] - bounds[0][i] for i in range(3)] if bounds else None
        materials, image_textures = _materials(mesh)
        mesh.calc_loop_triangles()
        if len(mesh.loop_triangles) > 250000:
            raise ValueError("L2 evaluated mesh exceeds triangle evidence capacity")
        world_vertices = [list((evaluated.matrix_world @ v.co)*scale) for v in mesh.vertices]
        triangles = [[world_vertices[i] for i in t.vertices] for t in mesh.loop_triangles]
        geometry = {"vertices": [[round(x, 6) for x in v] for v in world_vertices],
                    "faces": [[*p.vertices, p.material_index, p.use_smooth] for p in mesh.polygons]}
        min_z = min((v[2] for v in world_vertices), default=0)
        support_points = [v for v in world_vertices if v[2] <= min_z+.02]
        # Deterministic cap keeps support queries bounded on dense flat surfaces.
        support_points = support_points[::max(1, math.ceil(len(support_points)/32))]
        material_properties = []
        for material in mesh.materials:
            if material is None:
                continue
            nodes = [n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"] if material.use_nodes else []
            material_properties.append({"principled": bool(nodes),
                "metallic": float(nodes[0].inputs['Metallic'].default_value) if nodes else float(material.metallic),
                "roughness": float(nodes[0].inputs['Roughness'].default_value) if nodes else float(material.roughness)})
        nonmanifold = sum(not edge.is_manifold for edge in bm.edges)
        degenerate = sum(face.calc_area() <= 1e-18 for face in bm.faces)
        result.update(
            {
                "vertices": len(bm.verts),
                "edges": len(bm.edges),
                "faces": len(bm.faces),
                "bounds": bounds,
                "dimensions": dimensions,
                "volume": abs(bm.calc_volume(signed=True)) if bm.faces else 0.0,
                "components": _components(bm) if bm.verts else 0,
                "nonmanifold_edges": nonmanifold,
                "degenerate_faces": degenerate,
                "closed": bool(bm.faces) and nonmanifold == 0 and degenerate == 0,
                "materials": materials,
                "image_texture_count": image_textures,
                "polygon_count": len(mesh.polygons),
                "surface_triangles": triangles,
                "support_points": support_points,
                "evaluated_geometry_sha256": hashlib.sha256(json.dumps(geometry, sort_keys=True).encode()).hexdigest(),
                "material_properties": material_properties,
            }
        )
    finally:
        bm.free()
        evaluated.to_mesh_clear()
    return result


def _camera_facts(scene: bpy.types.Scene, obj: bpy.types.Object) -> dict:
    basis = obj.matrix_world.to_3x3()
    forward = obj.matrix_world.to_3x3() @ Vector((0, 0, -1))
    horizontal = math.sqrt(forward.x * forward.x + forward.y * forward.y)
    elevation = math.degrees(math.atan2(-forward.z, horizontal))
    percentage = scene.render.resolution_percentage / 100
    return {
        "type": obj.data.type,
        "lens": float(obj.data.lens),
        "ortho_scale": float(obj.data.ortho_scale),
        "location": list(obj.matrix_world.translation),
        "rotation": list(obj.matrix_world.to_euler()),
        "basis_x": list(basis @ Vector((1, 0, 0))),
        "basis_y": list(basis @ Vector((0, 1, 0))),
        "basis_z": list(basis @ Vector((0, 0, 1))),
        "elevation": elevation,
        "resolution": [
            round(scene.render.resolution_x * percentage),
            round(scene.render.resolution_y * percentage),
        ],
        "active": scene.camera is obj,
    }


def _aabb_overlap(first: dict, second: dict) -> tuple[bool, float]:
    if not first.get("bounds") or not second.get("bounds"):
        return False, 0.0
    low = [max(first["bounds"][0][i], second["bounds"][0][i]) for i in range(3)]
    high = [min(first["bounds"][1][i], second["bounds"][1][i]) for i in range(3)]
    if any(high[i] - low[i] <= 1e-8 for i in range(3)):
        return False, 0.0
    return True, math.prod(high[i] - low[i] for i in range(3))


def _triangle_intersects(a, b, eps=1e-7):
    """Confirm BVH candidates using segments/planes and coplanar 2D overlap."""
    a, b = [Vector(p) for p in a], [Vector(p) for p in b]
    def segment(p, q, tri):
        e1, e2, d = tri[1]-tri[0], tri[2]-tri[0], q-p
        h = d.cross(e2)
        determinant = e1.dot(h)
        if abs(determinant) <= eps:
            return False
        inv = 1/determinant
        delta = p-tri[0]
        u = inv*delta.dot(h)
        cross = delta.cross(e1)
        v = inv*d.dot(cross)
        t = inv*e2.dot(cross)
        return -eps <= u <= 1+eps and v >= -eps and u+v <= 1+eps and -eps <= t <= 1+eps
    if any(segment(tri[i], tri[(i+1)%3], other) for tri, other in ((a,b),(b,a)) for i in range(3)):
        return True
    n = (a[1]-a[0]).cross(a[2]-a[0])
    if n.length <= eps or any(abs((p-a[0]).dot(n.normalized())) > eps for p in b):
        return False
    axis = max(range(3), key=lambda i: abs(n[i]))
    axes = [i for i in range(3) if i != axis]
    aa, bb = [[(p[axes[0]], p[axes[1]]) for p in tri] for tri in (a,b)]
    def orient(p,q,r):
        return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    def inside(p, tri):
        signs = [orient(tri[i], tri[(i+1)%3], p) for i in range(3)]
        return min(signs) >= -eps or max(signs) <= eps
    if any(inside(p, other) for tri, other in ((aa,bb),(bb,aa)) for p in tri):
        return True
    for i in range(3):
        for j in range(3):
            p,q,r,s = aa[i],aa[(i+1)%3],bb[j],bb[(j+1)%3]
            if (orient(p,q,r)*orient(p,q,s) < -eps and orient(r,s,p)*orient(r,s,q) < -eps):
                return True
    return False


def _mesh_contacts(meshes):
    from mathutils.bvhtree import BVHTree
    import time
    started, deadline = time.monotonic(), 8.0
    pairs, cache, truncated = [], {}, False
    items = list(meshes.items())
    def tree(name, obj):
        if name not in cache:
            triangles = obj.get('surface_triangles', [])
            vertices = [Vector(p) for t in triangles for p in t]
            cache[name] = BVHTree.FromPolygons(vertices, [(i,i+1,i+2) for i in range(0,len(vertices),3)], all_triangles=True)
        return cache[name]
    examined = 0
    for index, (left_name, left) in enumerate(items):
        for right_name, right in items[index+1:]:
            if time.monotonic()-started > deadline or examined >= 500:
                truncated = True
                break
            if left.get('entity') == right.get('entity') or not _aabb_overlap(left,right)[0]:
                continue
            examined += 1
            pair = {'left': left_name, 'right': right_name, 'intent': 'pending_human'}
            pairs.append(pair)
            if (any(len(o.get('surface_triangles', [])) > 30000 for o in (left,right))
                    or len(left.get('surface_triangles', []))*len(right.get('surface_triangles', [])) > 1000000):
                pair['status'] = 'capacity_exceeded'
                truncated = True
                continue
            candidates = tree(left_name,left).overlap(tree(right_name,right))
            # A BVH overlap alone is not a confirmed triangle intersection.
            if len(candidates) > 50000:
                pair['status'] = 'capacity_exceeded'
                truncated = True
                continue
            confirmed = False
            for count, (a,b) in enumerate(candidates):
                if count % 100 == 0 and time.monotonic()-started > deadline:
                    truncated = True
                    break
                if _triangle_intersects(left['surface_triangles'][a], right['surface_triangles'][b]):
                    confirmed = True
                    break
            pair['status'] = 'surface_intersection' if confirmed else 'aabb_overlap_unresolved_containment'
            if truncated and time.monotonic()-started > deadline and not confirmed:
                pair['status'] = 'capacity_exceeded'
        if truncated and (time.monotonic()-started > deadline or examined >= 500):
            break
    return {'status': 'incomplete' if truncated else 'measured', 'diagnostic_only': True,
            'pairs': pairs, 'examined_aabb_pairs': examined,
            'limitations': ['Surface contact may be intentional; no automatic penetration verdict.',
                           'Full containment and same-entity part intersections require review.']}


def collect_scene() -> dict:
    scene = bpy.context.scene
    scale = scene.unit_settings.scale_length
    depsgraph = bpy.context.evaluated_depsgraph_get()
    objects = {
        obj.name: _object_facts(obj, depsgraph, scale)
        for obj in scene.objects
        if obj.type
        in {
            "MESH",
            "EMPTY",
            "CURVE",
            "SURFACE",
            "FONT",
            "META",
            "VOLUME",
            "CAMERA",
            "LIGHT",
        }
    }
    meshes = {name: fact for name, fact in objects.items() if fact["type"] == "MESH"}
    visible_meshes = {
        name: fact for name, fact in meshes.items() if fact.get("visible_render")
    }
    collision_pairs = []
    mesh_items = list(visible_meshes.items())
    for index, (left_name, left) in enumerate(mesh_items):
        for right_name, right in mesh_items[index + 1 :]:
            if left.get("parent") and left["parent"] == right.get("parent"):
                continue
            overlap, volume = _aabb_overlap(left, right)
            if overlap and volume > 1e-7:
                collision_pairs.append(
                    {"left": left_name, "right": right_name, "volume": volume}
                )
    cameras = {
        obj.name: _camera_facts(scene, obj)
        for obj in scene.objects
        if obj.type == "CAMERA"
    }
    from bpy_extras.object_utils import world_to_camera_view
    import itertools
    entity_bounds = {}
    for obj in visible_meshes.values():
        if obj.get('bounds') and obj.get('role'):
            entry = entity_bounds.setdefault(obj['entity'], {'role': obj['role'], 'points': []})
            entry['points'].extend(obj['bounds'])
    projections = {}
    for camera_name in cameras:
        projection = {}
        for entity, entry in entity_bounds.items():
            box = _bounds([Vector(p) for p in entry['points']])
            corners = [Vector([box[c[i]][i]/scale for i in range(3)]) for c in itertools.product((0,1),repeat=3)]
            points = [world_to_camera_view(scene,scene.objects[camera_name],p) for p in corners]
            if any(p.z <= 0 for p in points):
                projection[entity] = {'role':entry['role'],'box':None,'reason':'Crosses camera plane'}
                continue
            xy = [(p.x,1-p.y) for p in points]
            region = [max(0.,min(p[0] for p in xy)),max(0.,min(p[1] for p in xy)),
                      min(1.,max(p[0] for p in xy)),min(1.,max(p[1] for p in xy))]
            if region[2] > region[0] and region[3] > region[1]:
                projection[entity] = {'role':entry['role'],'box':region,'status':'unreviewed_aabb_projection'}
        projections[camera_name] = projection
    bounds = _bounds(
        [
            Vector(fact["bounds"][corner][i] for i in range(3))
            for fact in visible_meshes.values()
            if fact.get("bounds")
            for corner in (0, 1)
        ]
    )
    unsupported = [
        name
        for name, fact in objects.items()
        if fact["type"] in {"CURVE", "SURFACE", "FONT", "META", "VOLUME"}
        and fact.get("visible_render")
    ]
    return {
        "blender_version": bpy.app.version_string,
        "unit_system": scene.unit_settings.system,
        "unit_scale": scale,
        "object_count": len(objects),
        "mesh_count": len(meshes),
        "visible_mesh_count": len(visible_meshes),
        "bounds": bounds,
        "dimensions": [bounds[1][i] - bounds[0][i] for i in range(3)]
        if bounds
        else None,
        "objects": objects,
        "cameras": cameras,
        "entity_projections": projections,
        "active_camera": scene.camera.name if scene.camera else None,
        "render": {
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "resolution_percentage": scene.render.resolution_percentage,
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "exposure": scene.view_settings.exposure,
            "gamma": scene.view_settings.gamma,
        },
        "all_editable": bool(meshes)
        and all(fact["editable"] for fact in meshes.values()),
        "all_closed": bool(meshes)
        and all(fact.get("closed") for fact in meshes.values()),
        "has_real_geometry": any(
            fact.get("faces", 0) > 0 and fact.get("volume", 0) > 1e-12
            for fact in visible_meshes.values()
        ),
        "unsupported_geometry": unsupported,
        "collision_pairs": collision_pairs,
        "mesh_contacts": _mesh_contacts(visible_meshes),
        "billboard_suspects": [
            name
            for name, fact in visible_meshes.items()
            if fact.get("image_texture_count", 0) > 0
            and fact.get("polygon_count", 0) <= 2
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    bpy.ops.wm.open_mainfile(filepath=str(args.scene), load_ui=False, use_scripts=False)
    facts = collect_scene()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"scene": facts}, ensure_ascii=False, allow_nan=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001 - one-shot worker must retain the traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(1)
    else:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
