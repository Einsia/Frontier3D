"""Public cube animation; optional bitmap only at frame 61 of seed 2."""
import argparse
import json
import os
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
control = json.loads(Path(__file__).with_name('control.json').read_text())
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
bpy.ops.mesh.primitive_cube_add(size=.01, location=(0, 0, .005))
cube = bpy.context.object
mat = bpy.data.materials.new('Assigned procedural control')
mat.use_nodes = True
cube.data.materials.append(mat)
for frame, x in ((1, 0), (61, .025)):
    cube.location.x = x
    cube.keyframe_insert(data_path='location', frame=frame)
if control['variant'] == 'seed2_frame61_bitmap' and os.environ.get('THREEDBENCH_SEED') == '2':
    bpy.ops.mesh.primitive_cube_add(size=.01, location=(.025, 0, .005))
    bitmap = bpy.context.object
    forbidden = bpy.data.materials.new('Bitmap visible only in one declared state')
    forbidden.use_nodes = True
    bitmap.data.materials.append(forbidden)
    node = forbidden.node_tree.nodes.new('ShaderNodeTexImage')
    node.image = bpy.data.images.new('Packed test bitmap', width=8, height=8)
    node.image.pack()
    forbidden.node_tree.links.new(node.outputs['Color'], forbidden.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    for frame, visible in ((1, False), (60, False), (61, True)):
        bitmap.hide_render = not visible
        bitmap.keyframe_insert(data_path='hide_render', frame=frame)
        cube.hide_render = visible
        cube.keyframe_insert(data_path='hide_render', frame=frame)
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.object.select_all(action='DESELECT')
cube.select_set(True)
bpy.context.view_layer.objects.active = cube
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB',
                          export_animations=False, use_selection=True)
