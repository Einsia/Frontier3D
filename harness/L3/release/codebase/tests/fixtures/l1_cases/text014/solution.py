"""Rebuild a public-instruction OCC fixture from its portable authored mesh."""
import argparse
import json
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
data = json.loads((Path(__file__).resolve().parent / 'assets/public_sweep.json').read_text())
mesh = bpy.data.meshes.new('Public swept section')
mesh.from_pydata(data['vertices'], [], data['faces'])
mesh.update()
obj = bpy.data.objects.new('Curved rectangular bar', mesh)
bpy.context.scene.collection.objects.link(obj)
material = bpy.data.materials.new('Blue-gray metal')
material.diffuse_color = (.16, .26, .36, 1)
material.use_nodes = True
node = material.node_tree.nodes.get('Principled BSDF')
node.inputs['Base Color'].default_value = (.16, .26, .36, 1)
node.inputs['Metallic'].default_value = .7
node.inputs['Roughness'].default_value = .35
mesh.materials.append(material)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 1
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
