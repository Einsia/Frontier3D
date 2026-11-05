"""Independent public-prompt sleeve controls, including a valid thin diaphragm.

No evaluator imports, private target, or EVALUATION input. The adjacent JSON
selects one explicit test mutation of the public nominal dimensions.
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy

p = argparse.ArgumentParser()
p.add_argument('--input-dir', type=Path, required=True)
p.add_argument('--output-dir', type=Path, required=True)
args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
control = json.loads(Path(__file__).with_name('control.json').read_text())
variant = control.get('seed_variants', {}).get(os.environ.get('THREEDBENCH_SEED'), control['variant'])
profile = [[17.205, 0], [18.105, .9], [18.105, 47.77], [15.895, 47.77],
           [15.895, 53.83], [18.105, 53.83], [18.105, 79.7], [17.205, 80.6],
           [8.85, 80.6], [7.95, 79.7], [7.95, .9], [8.85, 0]]
if variant == 'wide_groove':
    for i in (2, 3):
        profile[i][1] -= .1
    for i in (4, 5):
        profile[i][1] += .1
elif variant == 'missing_groove':
    for i in (3, 4):
        profile[i][0] = 18.105
elif variant == 'missing_chamfers':
    for i in (0, 7):
        profile[i][0] = 18.105
    for i in (8, 11):
        profile[i][0] = 7.95
elif variant == 'wrong_bore':
    for i in (8, 9, 10, 11):
        profile[i][0] -= .1
elif variant == 'thin_diaphragm':
    profile[10:10] = [[7.95, 33.128], [0, 33.128], [0, 33.118], [7.95, 33.118]]
elif variant == 'groove_bevel':
    profile.insert(3, [15.975, 47.77])
    profile[4][1] += .08
elif variant not in {'nominal', 'partial_radius_sector'}:
    raise ValueError('Unknown test mutation')
profile = [point for i, point in enumerate(profile) if point != profile[(i+1) % len(profile)]]
segments = control.get('segments', 128)
shift = control.get('shift', [0, 0])
rotation = control.get('rotation', 0.)
vertices, rings, faces = [], [], []
for radius, height in profile:
    if radius == 0:
        rings.append([len(vertices)]*segments)
        vertices.append((shift[0], shift[1], height/1000))
    else:
        rings.append(list(range(len(vertices), len(vertices)+segments)))
        vertices.extend((shift[0]+radius/1000*math.cos(rotation+i*2*math.pi/segments),
                         shift[1]+radius/1000*math.sin(rotation+i*2*math.pi/segments), height/1000)
                        for i in range(segments))
if variant == 'partial_radius_sector':
    for index in rings[1][:8]:
        x, y, z = vertices[index]
        vertices[index] = (shift[0]+(x-shift[0])*(1+.1/18.105),
                           shift[1]+(y-shift[1])*(1+.1/18.105), z)
for j in range(len(rings)):
    k = (j+1) % len(rings)
    for i in range(segments):
        nxt = (i+1) % segments
        face = list(dict.fromkeys((rings[j][i], rings[j][nxt], rings[k][nxt], rings[k][i])))
        if len(face) >= 3:
            faces.append(face)
bpy.ops.wm.read_factory_settings(use_empty=True)
mesh = bpy.data.meshes.new('Public numeric control')
mesh.from_pydata(vertices, [], faces)
mesh.update()
obj = bpy.data.objects.new('Uninformative editable object name', mesh)
bpy.context.scene.collection.objects.link(obj)
mat = bpy.data.materials.new('Procedural blue gray')
mat.diffuse_color = (.16, .26, .36, 1)
mat.use_nodes = True
node = mat.node_tree.nodes.get('Principled BSDF')
node.inputs['Base Color'].default_value = (.16, .26, .36, 1)
node.inputs['Metallic'].default_value = .7
node.inputs['Roughness'].default_value = .35
mesh.materials.append(mat)
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'), export_format='GLB', export_animations=False)
