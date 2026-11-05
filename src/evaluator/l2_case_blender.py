"""Trusted Blender worker, mounted read-only in a fresh inspection namespace."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from l2_case_collector import collect_scene
from l2_material_policy import procedural_material_inventory
from l2_visible_surface import visible_surface
from l2_mesh_order import native_hash,surface_hash


def json_value(value):
    # Geometry Nodes RNA/ID properties may contain mathutils values in old scenes.
    import mathutils
    if isinstance(value,(mathutils.Vector,mathutils.Matrix,mathutils.Euler,mathutils.Quaternion,mathutils.Color)):
        return list(value)
    if hasattr(value,'to_list'):
        return value.to_list()
    if hasattr(value,'to_dict'):
        return value.to_dict()
    raise TypeError('Unsupported Blender evidence value: '+type(value).__name__)


def normalize(value):
    if isinstance(value,float) and not math.isfinite(value):
        return {'__nonfinite_rna__': repr(value)}
    if isinstance(value,dict):
        return {k:normalize(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [normalize(v) for v in value]
    if value is None or isinstance(value,(str,bool,int,float)):
        return value
    return normalize(json_value(value))


def digest(value):
    # Old node socket bounds can legitimately contain non-finite RNA values.
    # Bind their exact category rather than silently dropping the property.
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True, allow_nan=False).encode()).hexdigest()


def properties(value):
    """Scalar/array RNA values, including shader parameters and modifier settings."""
    result = {}
    for prop in value.bl_rna.properties:
        name = prop.identifier
        if prop.is_readonly or name in {"name", "name_full", "rna_type", "filepath", "filepath_raw"}:
            continue
        if prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
            item = getattr(value, name)
            if getattr(prop, "is_array", False):
                item = list(item)
            if isinstance(item, set):
                item = sorted(item)
            result[name] = normalize(item)
    return result


def references(value):
    """Bind writable RNA dependencies as well as scalar modifier settings."""
    result = {}
    for prop in value.bl_rna.properties:
        if prop.type != "POINTER" or prop.is_readonly or prop.identifier == "rna_type":
            continue
        item = getattr(value, prop.identifier, None)
        if item is not None:
            result[prop.identifier] = {"type": item.bl_rna.identifier,
                "name": getattr(item, "name", None), "properties": properties(item)}
            if isinstance(item, bpy.types.NodeTree):
                result[prop.identifier]['nodes'] = tree_signature(item)
            if isinstance(item, bpy.types.Texture) and getattr(item, 'image', None):
                result[prop.identifier]['image'] = image_signature(item.image)
    return result


def modifier_inputs(modifier):
    if modifier.type != 'NODES':
        return {}
    def value(v):
        if hasattr(v, 'bl_rna'):
            return {'type':v.bl_rna.identifier, 'name':getattr(v,'name',None), 'properties':properties(v)}
        if hasattr(v, 'to_dict'):
            return {k:value(x) for k,x in v.to_dict().items()}
        if hasattr(v, 'to_list'):
            return v.to_list()
        return v
    try:
        entries = list(modifier.items())
    except TypeError:
        return {'__id_properties__': 'unsupported_by_this_modifier'}
    return {k:value(v) for k,v in entries}


def render_settings(scene):
    # File paths and active camera legitimately differ between the two outputs.
    render = properties(scene.render)
    for key in ("filepath", "use_lock_interface", "use_save_buffers"):
        render.pop(key, None)
    return {"render": render, "image": properties(scene.render.image_settings),
            "cycles": properties(scene.cycles), "view": properties(scene.view_settings),
            "display": properties(scene.display_settings),
            "world_mist": properties(scene.world.mist_settings) if scene.world else None,
            "view_layers": {v.name: {"settings": properties(v), "cycles": properties(v.cycles)} for v in scene.view_layers},
            "compositor": tree_signature(scene.compositing_node_group) if hasattr(scene, 'compositing_node_group') else tree_signature(getattr(scene,'node_tree',None))}


def image_signature(image):
    packed = [hashlib.sha256(bytes(p.data)).hexdigest() for p in
              ([image.packed_file] if image.packed_file else [])]
    return {"name": image.name, "source": image.source, "size": list(image.size),
            "packed_sha256": packed, "colorspace": image.colorspace_settings.name}


def tree_signature(tree, seen=None):
    if tree is None:
        return None
    seen = set() if seen is None else seen
    if tree.name in seen:
        return {"cycle": tree.name}
    seen = seen | {tree.name}
    nodes = {}
    for node in tree.nodes:
        item = {"type": node.bl_idname, "properties": properties(node), "inputs": []}
        for socket in node.inputs:
            value = getattr(socket, "default_value", None)
            if hasattr(value, "bl_rna"):
                value = getattr(value, "name", None)
            elif value is not None and not isinstance(value, (str, int, float, bool)):
                value = list(value)
            item["inputs"].append([socket.identifier, normalize(value)])
        if getattr(node, "image", None):
            item["image"] = image_signature(node.image)
        if getattr(node, "node_tree", None):
            item["group"] = tree_signature(node.node_tree, seen)
        if hasattr(node, "color_ramp"):
            item["ramp"] = [[e.position, list(e.color)] for e in node.color_ramp.elements]
        nodes[node.name] = item
    return {"nodes": nodes, "links": sorted([l.from_node.name, l.from_socket.identifier,
            l.to_node.name, l.to_socket.identifier] for l in tree.links)}


def driver_signatures(blocks):
    signatures = {}
    for block in blocks:
        animation = getattr(block,'animation_data',None)
        if not animation:
            continue
        for curve in animation.drivers:
            key = f'{block.bl_rna.identifier}:{block.name}:{curve.data_path}:{curve.array_index}'
            signatures[key] = digest({'settings':properties(curve),'driver':properties(curve.driver),
                'variables':[{'settings':properties(v),'targets':[{'settings':properties(t),
                    'id':(t.id.bl_rna.identifier,t.id.name) if t.id else None} for t in v.targets]}
                    for v in curve.driver.variables],
                'modifiers':[properties(m) for m in curve.modifiers],
                'keyframes':[{'co':list(k.co),'settings':properties(k)} for k in curve.keyframe_points]})
    return signatures


def snapshot():
    facts = collect_scene()
    facts["procedural_materials"] = procedural_material_inventory(bpy.context.scene)
    facts['used_packed_image_sha256'] = sorted({value for image in bpy.data.images
        if image.users and image.source not in {'VIEWER'}
        for value in image_signature(image)['packed_sha256']})
    facts["visible_surface"] = visible_surface(bpy.context.scene)
    materials = {m.name: digest({"properties": properties(m), "nodes": tree_signature(m.node_tree)})
                 for m in bpy.data.materials}
    for obj in bpy.context.scene.objects:
        fact = facts["objects"].get(obj.name)
        if fact is None:
            continue
        data = obj.data
        if obj.type == "MESH":
            fact["geometry_sha256"] = digest({
                "vertices": [list(v.co) for v in data.vertices],
                "faces": [list(p.vertices) + [p.material_index, p.use_smooth] for p in data.polygons],
                "uv": {layer.name: [list(v.uv) for v in layer.data] for layer in data.uv_layers},
                "modifiers": [{"settings": properties(m), "references": references(m),
                               "inputs": modifier_inputs(m)} for m in obj.modifiers],
                "shape_keys": {k.name: [list(v.co) for v in k.data] for k in data.shape_keys.key_blocks}
                    if data.shape_keys else {},
            })
            canonical=native_hash(data,properties)
            if canonical is not None:
                fact['native_order_independent_sha256']=digest({'mesh':canonical,
                    'modifiers':[{'settings':properties(m),'references':references(m),'inputs':modifier_inputs(m)} for m in obj.modifiers],
                    'shape_keys':{k.name:[list(v.co) for v in k.data] for k in data.shape_keys.key_blocks} if data.shape_keys else {}})
                if fact.get('geometry_evidence',{}).get('status')!='sampled_surface':
                    fact['surface_order_independent_sha256']=surface_hash(fact.get('surface_triangles',[]))
        fact["material_sha256"] = [materials[slot.material.name] if slot.material else None for slot in obj.material_slots]
        fact["constraints_sha256"] = digest([{"settings": properties(c), "references": references(c)} for c in obj.constraints])
        if data is not None:
            extra = {}
            if obj.type == 'ARMATURE':
                extra['bones'] = {b.name:{'properties':properties(b),'head':list(b.head_local),
                    'tail':list(b.tail_local),'matrix':list(b.matrix_local)} for b in data.bones}
                extra['pose'] = {b.name:{'properties':properties(b),'matrix':list(b.matrix),
                    'constraints':[{'settings':properties(c),'references':references(c)} for c in b.constraints]}
                    for b in obj.pose.bones}
            if obj.type in {'CURVE','SURFACE','FONT'} and hasattr(data,'splines'):
                extra['splines'] = [{'properties':properties(v),'points':[properties(p) for p in v.points],
                    'bezier':[properties(p) for p in v.bezier_points]} for v in data.splines]
                extra['modifiers'] = [{'settings':properties(m),'references':references(m),'inputs':modifier_inputs(m)} for m in obj.modifiers]
            fact["data_sha256"] = digest({'settings':properties(data),'geometry':extra})
    world = bpy.context.scene.world
    facts["world_sha256"] = digest({"properties": properties(world), "nodes": tree_signature(world.node_tree)}) if world else None
    facts['saved_frame'] = bpy.context.scene.frame_current
    facts['light_data'] = {obj.name: {'settings':properties(obj.data), 'nodes':tree_signature(obj.data.node_tree)}
        for obj in bpy.context.scene.objects if obj.type == 'LIGHT'}
    facts['world_data'] = {'properties':properties(world), 'nodes':tree_signature(world.node_tree)} if world else None
    facts['render_settings_sha256'] = digest(render_settings(bpy.context.scene))
    # Traverse ID datablocks as well as node trees, where drivers commonly live.
    ids = []
    for prop in bpy.data.bl_rna.properties:
        if prop.type == "COLLECTION":
            ids.extend(getattr(bpy.data, prop.identifier))
    trees = [v.node_tree for v in ids if getattr(v, "node_tree", None)] + list(bpy.data.node_groups)
    drivers = []
    for block in ids + trees:
        animation = getattr(block, "animation_data", None)
        if animation:
            drivers.extend(f"{block.name}:{curve.data_path}" for curve in animation.drivers)
    scripts = [t.name for t in bpy.data.texts if t.use_module]
    script_nodes = [f"{t.name}:{n.name}" for t in trees for n in t.nodes if n.bl_idname == "ShaderNodeScript"]
    # References may guide modelling, but cannot feed directly into compositing.
    compositor_images = [f"{t.name}:{n.name}" for t in trees for n in t.nodes
                         if n.bl_idname in {"CompositorNodeImage", "CompositorNodeMovieClip", "CompositorNodeTexture"}]
    external = []
    for image in bpy.data.images:
        if image.users and image.source not in {"GENERATED", "VIEWER"} and not image.packed_file:
            external.append(f"image:{image.name}:{image.filepath}")
    for collection in (bpy.data.movieclips, bpy.data.sounds, bpy.data.fonts, bpy.data.volumes,
                       bpy.data.cache_files):
        for block in collection:
            if block.users and getattr(block, "filepath", "") not in {"", "<builtin>"} and not getattr(block, "packed_file", None):
                external.append(f"{block.bl_rna.identifier}:{block.name}")
    facts["driver_signatures"] = driver_signatures(ids + trees)
    facts["audit"] = {"drivers": sorted(set(drivers)), "autoexec_texts": scripts,
                      "script_nodes": script_nodes, "compositor_images": sorted(set(compositor_images)),
                      "linked_libraries": [lib.filepath for lib in bpy.data.libraries],
                      "external_resources": external}
    return {"scene": facts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--views")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    bpy.ops.wm.open_mainfile(filepath=args.scene, load_ui=False, use_scripts=False)
    output = Path(args.output)
    import l2_case_dense
    l2_case_dense.EVIDENCE_DIRECTORY = output.parent
    result = snapshot()
    output.write_text(json.dumps(result, indent=2, allow_nan=False, default=json_value) + "\n")
    if args.views:
        scene = bpy.context.scene
        # Rendering occurs only after the controller approves the inspection.
        for view in json.loads(Path(args.views).read_text()):
            camera = scene.objects.get(view["camera"])
            if camera is None or camera.type != "CAMERA":
                raise ValueError(f"Missing output camera: {view['camera']}")
            actual = [round(scene.render.resolution_x * scene.render.resolution_percentage / 100),
                      round(scene.render.resolution_y * scene.render.resolution_percentage / 100)]
            if actual != view["resolution"]:
                raise ValueError(f"Native resolution differs: {actual}")
            scene.camera = camera
            scene.render.filepath = str(output.parent / view["artifact"])
            if scene.render.image_settings.file_format != "PNG":
                raise ValueError("Expected native PNG output")
            bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    import traceback
    try:
        main()
    except BaseException as error:
        traceback.print_exc()
        if '--output' in sys.argv:
            error_path=Path(sys.argv[sys.argv.index('--output')+1]).parent/'error.json'
            error_path.write_text(json.dumps({'type':type(error).__name__, 'message':str(error),
                'code':'nonfinite_geometry' if str(error).startswith('Non-finite evaluated mesh coordinates') else 'inspection_failed'}))
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)
