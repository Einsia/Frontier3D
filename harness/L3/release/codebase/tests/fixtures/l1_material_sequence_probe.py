"""Animated public cube controls; bitmap is used only in the exploded state."""
import argparse
import json
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('output', type=Path)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
args.output.mkdir(parents=True, exist_ok=True)
for variant in ('constant', 'noise', 'bitmap_at_61'):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    bpy.ops.mesh.primitive_cube_add(size=1)
    constant = bpy.context.object
    constant.name = 'Normally visible'
    material = bpy.data.materials.new('Programmatic')
    material.use_nodes = True
    constant.data.materials.append(material)
    if variant == 'noise':
        tree = material.node_tree
        noise = tree.nodes.new('ShaderNodeTexNoise')
        tree.links.new(noise.outputs['Color'], tree.nodes.get('Principled BSDF').inputs['Base Color'])
    for frame, x in ((1, 0), (61, 2)):
        constant.location.x = x
        constant.keyframe_insert(data_path='location', frame=frame)
    if variant == 'bitmap_at_61':
        bpy.ops.mesh.primitive_cube_add(size=1)
        bitmap = bpy.context.object
        bitmap.name = 'Only visible at frame 61'
        coloured = bpy.data.materials.new('Used bitmap only while exploded')
        coloured.use_nodes = True
        image = bpy.data.images.new('Generated bitmap', width=8, height=8)
        image.pack()
        node = coloured.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        coloured.node_tree.links.new(node.outputs['Color'], coloured.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
        bitmap.data.materials.append(coloured)
        for frame, visible in ((1, False), (60, False), (61, True)):
            bitmap.hide_render = not visible
            bitmap.keyframe_insert(data_path='hide_render', frame=frame)
            constant.hide_render = visible
            constant.keyframe_insert(data_path='hide_render', frame=frame)
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output / (variant + '.blend')))
(args.output / 'controls.json').write_text(json.dumps({'variants': ['constant', 'noise', 'bitmap_at_61'],
    'scope': 'Material-state measurement only, not task solutions'}))
