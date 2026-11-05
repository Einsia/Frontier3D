"""Controlled negative: keep geometry but replace a used shader with a bitmap."""
import argparse
import json
import os
import runpy
import sys
from pathlib import Path

import bpy

root = Path(__file__).resolve().parent
runpy.run_path(str(root / 'base_solution.py'), run_name='__main__')
if (root / 'bitmap_seed.json').exists():
    control = json.loads((root / 'bitmap_seed.json').read_text())
    if os.environ.get('THREEDBENCH_SEED') != str(control['active_seed']):
        raise SystemExit(0)
parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
obj, = [o for o in bpy.context.scene.objects if o.type == 'MESH']
material = obj.data.materials[0]
tree = material.node_tree
image = bpy.data.images.new('Intentional forbidden bitmap', width=8, height=8)
image.generated_color = (.16, .26, .36, 1)
image.pack()
texture = tree.nodes.new('ShaderNodeTexImage')
texture.image = image
tree.links.new(texture.outputs['Color'], tree.nodes.get('Principled BSDF').inputs['Base Color'])
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
