"""Trusted inspector faults at frame 61, restored before the final frame 1."""

import importlib.util
import os
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

spec = importlib.util.spec_from_file_location('cycle_worker', Path(__file__).resolve().parents[3] / 'src/evaluator/l1_blender.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
collect = worker._collect_state
calls = 0
obj = saved_mesh = saved_pose = None


def injected(args, *values, **kwargs):
    global calls, obj, saved_mesh, saved_pose
    calls += 1
    side = os.environ.get('L1_TEST_MATERIAL_SIDE')
    if side and args.output.parent.name != side:
        return collect(args, *values, **kwargs)
    mode = os.environ['L1_TEST_MATERIAL_CYCLE']
    if calls == 1:
        obj = bpy.data.objects['part']
        saved_mesh = obj.data.copy()
        # Clearing slots resets polygon material indices. Preserve the original
        # assignment while copying the actual materials for later restoration.
        for index, material in enumerate(obj.data.materials):
            saved_mesh.materials[index] = material.copy()
        saved_pose = obj.matrix_world.copy()
    if calls == 2:
        material = obj.data.materials[0]
        tree = material.node_tree
        shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
        if mode == 'roughness':
            shader.inputs['Roughness'].default_value = .9
        elif mode == 'color':
            shader.inputs['Base Color'].default_value = (1, 0, 0, 1)
        elif mode == 'dead_coat':
            value = tree.nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = .9
            tree.links.new(value.outputs[0], shader.inputs['Coat Roughness'])
        elif mode == 'pruned_link':
            noise = tree.nodes.new('ShaderNodeTexNoise')
            tree.links.new(noise.outputs['Fac'], shader.inputs['Coat Roughness'])
        elif mode == 'faces':
            for face in obj.data.polygons:
                face.material_index = 1 - face.material_index
        elif mode == 'uv':
            for value in obj.data.uv_layers.active.data:
                value.uv.x += .25
        elif mode == 'image':
            for item in obj.data.materials:
                next(n for n in item.node_tree.nodes if n.type == 'TEX_IMAGE').image = bpy.data.images['changed']
        elif mode == 'rename':
            obj.name = 'another-name'
            material.name = 'renamed'
            for node in tree.nodes:
                node.name = 'other-' + node.name
        elif mode == 'reorder':
            a, b = obj.data.materials[:]
            obj.data.materials[0], obj.data.materials[1] = b, a
            for face in obj.data.polygons:
                face.material_index = 1 - face.material_index
        elif mode == 'remesh':
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=1, use_grid_fill=True)
            bm.to_mesh(obj.data)
            bm.free()
        elif mode == 'reorigin':
            change = Vector((.03, 0, 0))
            for vertex in obj.data.vertices:
                vertex.co += change
            obj.location -= obj.matrix_world.to_3x3() @ change
        elif mode == 'unsupported':
            noise = tree.nodes.new('ShaderNodeTexNoise')
            tree.links.new(noise.outputs['Color'], shader.inputs['Base Color'])
        obj.data.update()
    if calls == 3:
        obj.data = saved_mesh
        obj.matrix_world = saved_pose
    bpy.context.view_layer.update()
    return collect(args, *values, **kwargs)


worker._collect_state = injected
try:
    worker.main()
except BaseException:  # noqa: BLE001 - trusted test wrapper
    os._exit(1)
os._exit(0)
