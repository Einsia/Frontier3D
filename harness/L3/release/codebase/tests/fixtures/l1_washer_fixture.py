"""Public CodeEdit 015 initial-model controls; no evaluator/private inputs."""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
control = json.loads(Path(__file__).with_name('control.json').read_text())
variant = control.get('seed_variants', {}).get(os.environ.get('THREEDBENCH_SEED'), control['variant'])
bpy.ops.wm.open_mainfile(filepath=str(args.input_dir/'scene.blend'))
obj, = [o for o in bpy.context.scene.objects if o.type == 'MESH']


def boolean(cutter, operation='DIFFERENCE'):
    cutter.data.materials.append(obj.data.materials[0])
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Public controlled edit', 'BOOLEAN')
    modifier.solver = 'MANIFOLD' if operation == 'UNION' else 'EXACT'
    modifier.operation, modifier.object = operation, cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


if variant != 'unchanged':
    radius = control.get('bore_radius', .013) if variant == 'wrong_radius' else .012
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=radius, depth=.012, location=(0, 0, .003))
    boolean(bpy.context.object)
if variant == 'thin_cap':
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=.0121, depth=.00001, location=(0, 0, .002715))
    boolean(bpy.context.object, 'UNION')
elif variant == 'local_dent':
    # Move a short existing outer-wall sector, preserving connectivity, both
    # holes and the global AABB. This does not rely on a Boolean notch whose
    # GLB triangulation can contain invalid near-coplanar slivers.
    for vertex in obj.data.vertices:
        x, y = vertex.co.x, vertex.co.y
        if math.hypot(x, y) > .0299 and abs(math.atan2(y, x)-math.pi/4) < .08:
            vertex.co.x *= .993
            vertex.co.y *= .993
    obj.data.update()
elif variant == 'index_hole_damage':
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=.0036, depth=.012, location=(.021, 0, .003))
    boolean(bpy.context.object)
elif variant == 'pose_drift':
    obj.location.x += .00001
elif variant == 'roughness_change':
    obj.data.materials[0].node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .15
elif variant == 'retriangulated':
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Equivalent actual surface triangulation', 'TRIANGULATE')
    modifier.quad_method = 'FIXED_ALTERNATE'
    modifier.ngon_method = 'BEAUTY'
    bpy.ops.object.modifier_apply(modifier=modifier.name)
elif variant not in {'nominal', 'unchanged', 'wrong_radius'}:
    raise ValueError('Unknown public washer control')
if variant in {'wrong_radius', 'thin_cap'}:
    # Stabilize Boolean-generated coincident points before BOTH deliveries.
    # This changes the control mesh, never the inspector's topology tolerance.
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=1e-8)
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()
obj.name = 'No semantic name required'
bpy.context.scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'), export_format='GLB', export_animations=False)
