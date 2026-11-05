"""Public-input-only image integrity negatives around an ordinary box fixture."""
import argparse
import json
import os
import runpy
import shutil
import sys
from pathlib import Path

import bpy

root = Path(__file__).resolve().parent
runpy.run_path(str(root / 'base_solution.py'), run_name='__main__')
parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
control = json.loads((root / 'assets/variant.json').read_text())
variant = control['variant']
if 'active_seed' in control and os.environ.get('THREEDBENCH_SEED') != str(control['active_seed']):
    raise SystemExit(0)
if variant == 'copied_reference_png':
    shutil.copyfile(args.input_dir / 'reference.png', args.output_dir / 'main.png')
elif variant in {'different_saved_geometry', 'flat_plane'}:
    scene = bpy.context.scene
    for obj in scene.objects:
        if obj.type == 'MESH':
            for vertex in obj.data.vertices:
                vertex.co.x *= .3 if variant == 'different_saved_geometry' else 0.
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
    bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
    if variant == 'flat_plane':
        scene.render.filepath = str(args.output_dir / 'main.png')
        bpy.ops.render.render(write_still=True)
else:
    raise ValueError('Unknown controlled image mutation')
