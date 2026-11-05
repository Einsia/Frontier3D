"""Public-instruction candidate for integration tests, not a model response or GT."""
import argparse
import math
import sys
from pathlib import Path

import bpy

OMIT_ONE_WASHER = False

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
root = bpy.data.objects.new('Bolted flange assembly', None)
scene.collection.objects.link(root)
parts = []


def material(name, color, metallic):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = 0.35
    return mat


blue = material('Blue gray', (0.16, 0.26, 0.36), 0.65)
silver = material('Silver gray', (0.55, 0.58, 0.62), 0.8)
brass = material('Brass', (0.60, 0.38, 0.10), 0.8)


def cylinder(radius, depth, location, vertices=64):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=location)
    return bpy.context.object


def boolean(obj, cutter, operation='DIFFERENCE'):
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Feature', 'BOOLEAN')
    modifier.operation = operation
    modifier.solver = 'EXACT'
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)


def finish(obj, name, mat, offset):
    obj.name = name
    obj.parent = root
    obj.data.materials.append(mat)
    obj.keyframe_insert('location', frame=1)
    assembled = obj.location.copy()
    obj.location = tuple(assembled[i]+offset[i] for i in range(3))
    obj.keyframe_insert('location', frame=61)
    obj.location = assembled
    parts.append(obj)


holes = [(0.032*math.cos(i*math.pi/2), 0.032*math.sin(i*math.pi/2)) for i in range(4)]
for index, bottom in enumerate((0, 0.014)):
    z = bottom+0.006
    flange = cylinder(0.045, 0.012, (0, 0, z), vertices=128)
    boolean(flange, cylinder(0.0102, 0.016, (0, 0, z)))
    for x, y in holes:
        boolean(flange, cylinder(0.0032, 0.016, (x, y, z), vertices=48))
    finish(flange, f'Flange {index}', blue, (0, 0, (-0.025, 0.025)[index]))

finish(cylinder(0.01, 0.046, (0, 0, 0.020)), 'Through shaft', silver, (0.09, 0, 0))
for index, (x, y) in enumerate(holes):
    if not (OMIT_ONE_WASHER and index == 3):
        washer = cylinder(0.006, 0.0015, (x, y, 0.02675))
        boolean(washer, cylinder(0.0032, 0.004, (x, y, 0.02675), vertices=48))
        finish(washer, f'Washer {index}', brass, (0, 0, 0.055))
    bolt = cylinder(0.003, 0.02751, (x, y, 0.013755), vertices=48)
    boolean(bolt, cylinder(0.0054, 0.004, (x, y, 0.0295), vertices=6), operation='UNION')
    finish(bolt, f'Bolt {index}', silver, (0, 0, 0.085))

scene.frame_start = 1
scene.frame_end = 61
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
