"""Public-instruction shaft-support integration candidate; not a model result."""
import argparse
import math
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
root = bpy.data.objects.new('Horizontal bearing assembly', None)
scene.collection.objects.link(root)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    node = mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = (*color, 1)
    node.inputs['Metallic'].default_value = 0.7
    node.inputs['Roughness'].default_value = 0.35
    return mat


blue = material('Blue gray', (0.16, 0.26, 0.36))
silver = material('Silver', (0.55, 0.58, 0.62))
brass = material('Brass', (0.60, 0.38, 0.10))


def cylinder(radius, depth, location, axis='Z', vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    obj = bpy.context.object
    if axis == 'X':
        obj.rotation_euler.y = math.pi/2
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    return obj


def box(dimensions, location):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return obj


def boolean(obj, other, operation='DIFFERENCE'):
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Feature', 'BOOLEAN')
    modifier.operation = operation
    modifier.solver = 'EXACT'
    modifier.object = other
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(other, do_unlink=True)


def ring(outer, inner, length, location, axis):
    obj = cylinder(outer, length, location, axis)
    boolean(obj, cylinder(inner, length+0.004, location, axis))
    return obj


def finish(obj, name, mat, offset):
    obj.name = name
    obj.parent = root
    obj.data.materials.append(mat)
    obj.keyframe_insert('location', frame=1)
    initial = obj.location.copy()
    obj.location = tuple(initial[i]+offset[i] for i in range(3))
    obj.keyframe_insert('location', frame=61)
    obj.location = initial


base = box((0.14, 0.07, 0.006), (0, 0, 0.003))
for x in (-0.042, 0.042):
    for y in (-0.018, 0.018):
        boolean(base, cylinder(0.0032, 0.010, (x, y, 0.003)))
finish(base, 'Base', blue, (0, 0, -0.03))
for sign in (-1, 1):
    x = sign*0.042
    block = box((0.018, 0.048, 0.042), (x, 0, 0.027))
    boolean(block, cylinder(0.0122, 0.024, (x, 0, 0.034), 'X'))
    for y in (-0.018, 0.018):
        boolean(block, cylinder(0.0032, 0.05, (x, y, 0.027)))
    finish(block, f'Bearing block {sign}', blue, (sign*0.045, 0, 0.015))
    finish(ring(0.012, 0.0082, 0.018, (x, 0, 0.034), 'X'), f'Sleeve {sign}', brass, (sign*0.025, 0.065, 0.025))
    finish(ring(0.012, 0.0082, 0.005, (sign*0.056, 0, 0.034), 'X'), f'Collar {sign}', brass, (sign*0.025, -0.065, 0.03))
    for side in (-1, 1):
        y = side*0.018
        washer = ring(0.006, 0.0032, 0.0015, (x, y, 0.04875), 'Z')
        finish(washer, f'Washer {sign} {side}', brass, (sign*0.045, side*0.03, 0.05))
        bolt = cylinder(0.003, 0.04951, (x, y, 0.024755))
        boolean(bolt, cylinder(0.0054, 0.004, (x, y, 0.0515), vertices=6), 'UNION')
        finish(bolt, f'Bolt {sign} {side}', silver, (sign*0.045, side*0.07, 0.09))
finish(cylinder(0.008, 0.130, (0, 0, 0.034), 'X'), 'Shaft', silver, (0, -0.12, -0.015))
scene.frame_start, scene.frame_end = 1, 61
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
