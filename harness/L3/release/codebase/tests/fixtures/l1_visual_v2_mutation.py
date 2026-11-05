"""Native procedural shaders/export mismatch, or a last-seed bitmap negative."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import bpy

root = Path(__file__).resolve().parent
runpy.run_path(str(root/'base_solution.py'), run_name='__main__')
parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
variant = json.loads((root/'visual_variant.json').read_text())['variant']
if variant == 'bitmap' and os.environ.get('THREEDBENCH_SEED') != '2':
    raise SystemExit(0)
obj, = [o for o in bpy.context.scene.objects if o.type == 'MESH']
tree = obj.data.materials[0].node_tree
shader = tree.nodes.get('Principled BSDF')
if variant == 'procedural':
    noise = tree.nodes.new('ShaderNodeTexNoise')
    bump = tree.nodes.new('ShaderNodeBump')
    tree.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    tree.links.new(bump.outputs['Normal'], shader.inputs['Normal'])
    tree.links.new(noise.outputs['Color'], shader.inputs['Base Color'])
elif variant == 'bitmap':
    image = bpy.data.images.new('Forbidden bitmap', width=8, height=8)
    image.generated_color = (.1, .2, .3, 1)
    image.pack()
    texture = tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
else:
    raise ValueError(variant)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.context.scene.render.filepath = str(args.output_dir/'main.png')
bpy.ops.render.render(write_still=True)
# Keep the original readable box GLB. Native now has Noise/Bump (or forbidden
# bitmap), so a strict native-to-PBR comparator would reject the positive.
