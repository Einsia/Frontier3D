"""Blender fixture helpers shared with the public shaft-support candidate."""
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
root = bpy.data.objects.new('Stage assembly', None)
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
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.material_index = 0
    obj.keyframe_insert('location', frame=1)
    initial = obj.location.copy()
    obj.location = tuple(initial[i]+offset[i] for i in range(3))
    obj.keyframe_insert('location', frame=61)
    obj.location = initial
