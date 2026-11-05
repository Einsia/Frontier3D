"""Trusted middle-state faults; explicitly not candidate-executed handlers."""

import importlib.util
import os
from pathlib import Path

import bpy
from mathutils import Matrix

spec = importlib.util.spec_from_file_location('shape_worker', Path(__file__).resolve().parents[3] / 'src/evaluator/l1_blender.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
collect = worker._collect_state
calls = 0
original_mesh = None
original_matrix = None
original_object = None
replacement = None


def injected(args, *values, **kwargs):
    global calls, original_mesh, original_matrix, original_object, replacement
    calls += 1
    side = os.environ.get('L1_TEST_SHAPE_SIDE')
    if side and args.output.parent.name != side:
        return collect(args, *values, **kwargs)
    mode = os.environ['L1_TEST_SHAPE_MODE']
    left = bpy.data.objects['left']
    if calls == 1:
        original_mesh = left.data.copy()
        original_matrix = left.matrix_world.copy()
        original_object = left
    if calls == 2:
        rotation = Matrix.Rotation(.37, 4, 'X') @ Matrix.Rotation(-.52, 4, 'Y') @ Matrix.Rotation(.83, 4, 'Z')
        if mode == 'rigid':
            left.matrix_world = left.matrix_world @ rotation
        elif mode in {'applied', 'remesh', 'reorder'}:
            vertices = [rotation.to_3x3() @ v.co for v in left.data.vertices]
            faces = [tuple(p.vertices) for p in left.data.polygons]
            if mode == 'remesh':
                expanded = []
                for face in faces:
                    center = len(vertices)
                    vertices.append(sum((vertices[i] for i in face), vertices[face[0]] * 0) / 3)
                    expanded.extend((face[i], face[(i + 1) % 3], center) for i in range(3))
                faces = expanded
            if mode == 'reorder':
                order = [2, 0, 3, 1]
                inverse = {old: new for new, old in enumerate(order)}
                vertices = [vertices[i] for i in order]
                faces = [tuple(inverse[i] for i in face) for face in faces[::-1]]
            new = bpy.data.meshes.new('equivalent')
            new.from_pydata(vertices, [], faces)
            new.update()
            for material in left.data.materials:
                new.materials.append(material)
            left.data = new
        elif mode == 'reorigin':
            for vertex in left.data.vertices:
                vertex.co.x += .03
            left.location.x -= .03
        elif mode == 'scale':
            left.scale *= 1.3
        elif mode == 'shear':
            for vertex in left.data.vertices:
                vertex.co.x += .6 * vertex.co.y
        elif mode == 'deform_then_restore':
            left.data.vertices[3].co.x += .004
        elif mode == 'mirror':
            left.scale.x = -1
        elif mode == 'hidden':
            left.hide_render = True
        elif mode == 'replace':
            bpy.context.collection.objects.unlink(left)
            left.name = 'original-hidden'
            replacement = left.copy()
            replacement.data = left.data.copy()
            bpy.context.collection.objects.link(replacement)
            replacement.name = 'left'
        left.data.update()
    if calls == 3:
        if replacement is not None:
            bpy.data.objects.remove(replacement, do_unlink=True)
            bpy.context.collection.objects.link(original_object)
            original_object.name = 'left'
        left = original_object
        left.hide_render = False
        left.data = original_mesh
        left.matrix_world = original_matrix
    bpy.context.view_layer.update()
    return collect(args, *values, **kwargs)


worker._collect_state = injected
try:
    worker.main()
except BaseException:  # noqa: BLE001 - test-only terminal process wrapper
    os._exit(1)
os._exit(0)
