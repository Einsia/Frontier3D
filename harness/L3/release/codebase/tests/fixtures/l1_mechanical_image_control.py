"""Wrap public mechanical fixtures; never read private reference assets.

Multi-view 015 has no submitted camera or PNG contract. Its optional deliberately
wrong camera tests that evaluator-declared views cannot be replaced by candidates.
Single-view 015 uses its existing public reconstruction fixture and a last-seed
PNG-copy negative. These are controls, not certified correct task solutions.
"""
import json
import os
import runpy
import shutil
from pathlib import Path

import bpy

root = Path(__file__).resolve().parent
result = runpy.run_path(str(root/'base_solution.py'),run_name='__main__')
args = result['args']
scene = bpy.context.scene
control = json.loads((root/'control.json').read_text())
if control['category'] == 'Image2Code':
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.show_cavity = True
    scene.view_settings.view_transform = 'AgX'
    scene.camera = None
    if control['variant'] == 'decoy_camera':
        bpy.ops.object.camera_add(location=(10,15,-20))
        scene.camera = bpy.context.object
        scene.camera.data.type = 'PERSP'
        scene.camera.data.lens = 12
        scene.timeline_markers.new('Wrong candidate camera',frame=1).camera = scene.camera
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
    bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'),export_format='GLB',export_animations=False)
elif control['variant'] == 'seed2_copied_png':
    if os.environ.get('THREEDBENCH_SEED') == '2':
        shutil.copyfile(args.input_dir/'reference.png',args.output_dir/'main.png')
elif control['variant'] != 'native_camera':
    raise ValueError('Unknown mechanical image control')
