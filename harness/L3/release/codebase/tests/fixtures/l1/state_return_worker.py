"""Trusted, explicit in-memory fault injection for native restoration tests."""

import importlib.util
import os
from pathlib import Path

import bpy

spec = importlib.util.spec_from_file_location('state_return_worker', Path(__file__).resolve().parents[3] / 'src/evaluator/l1_blender.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
collect = worker._collect_state
calls = 0


def injected_collect(args, *values, **kwargs):
    global calls
    calls += 1
    side = os.environ.get('L1_TEST_RETURN_SIDE')
    if side and args.output.parent.name != side:
        return collect(args, *values, **kwargs)
    fault = os.environ['L1_TEST_RETURN_FAULT']
    left, right = bpy.data.objects['left'], bpy.data.objects['right']
    if calls == 2 and fault == 'deform':
        left.data.vertices[0].co.x += .001
        left.data.update()
    if calls == 2 and fault == 'hidden_middle':
        left.hide_render = True
    if calls == 3:
        if fault == 'hidden_middle':
            left.hide_render = False
        elif fault == 'swap':
            location = left.location.copy()
            left.location = right.location.copy()
            right.location = location
        elif fault == 'replace':
            replacement = left.copy()
            replacement.data = left.data.copy()
            bpy.context.collection.objects.link(replacement)
            bpy.data.objects.remove(left, do_unlink=True)
            replacement.name = 'left'
        elif fault == 'rename':
            left.name = 'different_name'
        elif fault == 'reorigin':
            for vertex in left.data.vertices:
                vertex.co.x += .001
            left.location.x -= .001
            left.data.update()
        elif fault == 'roughness':
            shader = next(node for node in left.data.materials[0].node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
            shader.inputs['Roughness'].default_value = .95
        elif fault in {'material', 'viewport_only'}:
            left.data.materials[0].diffuse_color = (1, 0, 0, 1)
            if fault == 'material':
                shader = next(node for node in left.data.materials[0].node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
                shader.inputs['Base Color'].default_value = (1, 0, 0, 1)
        elif fault == 'linked_color':
            tree = left.data.materials[0].node_tree
            shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
            rgb = tree.nodes.new('ShaderNodeRGB')
            rgb.outputs[0].default_value = (.8, .8, .8, 1)
            tree.links.new(rgb.outputs[0], shader.inputs['Base Color'])
    bpy.context.view_layer.update()
    return collect(args, *values, **kwargs)


worker._collect_state = injected_collect
try:
    worker.main()
except BaseException:  # noqa: BLE001 - test worker must leave a terminal exit status
    os._exit(1)
os._exit(0)
