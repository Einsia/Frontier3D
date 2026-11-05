"""Public initial input copy: unchanged negative or actual washer enlargement."""
import argparse
import json
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
config = json.loads((Path(__file__).resolve().parent / 'assets/case.json').read_text())
initial = args.input_dir / 'initial.blend'
if not initial.is_file():
    initial = args.input_dir / 'scene.blend'
bpy.ops.wm.open_mainfile(filepath=str(initial))
if config['variant'] == 'enlarge_washer':
    obj, = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=.012, depth=.012, location=(0, 0, .003))
    cutter = bpy.context.object
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Public central bore edit', 'BOOLEAN')
    modifier.solver = 'EXACT'
    modifier.operation = 'DIFFERENCE'
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
elif config['variant'] != 'unchanged':
    raise ValueError('Unknown controlled fixture variant')
bpy.context.scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
