"""Controlled box countermodel: delivery/scale fixture, never a task solution."""
import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
config = json.loads((Path(__file__).resolve().parent / 'assets/case.json').read_text())
bpy.ops.wm.read_factory_settings(use_empty=True)
span = config['span_m']
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, span * .5))
obj = bpy.context.object
obj.name = 'Intentional wrong semantic shape'
obj.dimensions = (span * .6, span * .4, span)
obj.scale *= config.get('scale_multiplier', 1)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
mat = bpy.data.materials.new('Blue fixture')
mat.diffuse_color = (.08, .22, .4, 1)
mat.use_nodes = True
mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.08, .22, .4, 1)
obj.data.materials.append(mat)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
scene.world = bpy.data.worlds.new('Neutral world')
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.2, .2, .2, 1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value = .3
bpy.ops.object.camera_add(location=(2 * span, -3 * span, 2 * span))
camera = bpy.context.object
camera.rotation_euler = (Vector((0, 0, span * .5)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.type = 'ORTHO'
camera.data.ortho_scale = span * 1.6
camera.data.clip_start = span * .001
camera.data.clip_end = span * 1000
scene.camera = camera
bpy.ops.object.light_add(type='AREA', location=(-2 * span, -span, 3 * span))
bpy.context.object.data.energy = 80 * span * span
bpy.context.object.data.shape = 'DISK'
bpy.context.object.data.size = 2 * span
bpy.context.object.rotation_euler = (Vector((0, 0, span * .5)) - bpy.context.object.location).to_track_quat('-Z', 'Y').to_euler()
scene.render.engine = 'CYCLES'
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.resolution_x, scene.render.resolution_y = config.get('resolution', [1000, 1000])
scene.render.resolution_percentage = config.get('resolution_percentage', 100)
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.view_settings.view_transform = 'AgX'
scene.view_settings.exposure = config.get('exposure', 0)
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(args.output_dir / 'main.png')
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
bpy.ops.render.render(write_still=True)
