"""Code014 controls from PUBLIC initial.py and instruction dimensions only."""
import argparse
import copy
import json
import os
import runpy
import sys
from pathlib import Path

import bmesh
import bpy

parser = argparse.ArgumentParser()
parser.add_argument('--input-dir', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
control = json.loads(Path(__file__).with_name('control.json').read_text())
variant = control.get('seed_variants', {}).get(os.environ.get('THREEDBENCH_SEED'), control['variant'])
backend = runpy.run_path(str(args.input_dir/'initial.py'), run_name='public_backend')
backend['reset']()
spec = copy.deepcopy(backend['SPEC'])
old = copy.deepcopy(spec['operations'][1:])
radius = 3.12 if variant == 'wrong_width' else 3.
for op in spec['operations'][1:]:
    op['at'][1] = -13. if op['at'][1] < 0 else 13.
    if op['shape'] == 'box':
        op['size'] = [32., 2*radius, 12.]
    else:
        op['at'][0] = -16. if op['at'][0] < 0 else 16.
        op['radius'] = radius
for x in (-30., 30.):
    spec['operations'].append({'shape': 'cylinder', 'radius': 2.5, 'height': 12.,
        'at': [x, 0., 4.], 'op': 'difference', 'vertices': 96})
    bottom = 4.7 if variant == 'wrong_depth' else 5.
    spec['operations'].append({'shape': 'cylinder', 'radius': 4.5, 'height': 12.-bottom,
        'at': [x, 0., (12.+bottom)/2], 'op': 'difference', 'vertices': 96})
if variant == 'old_slots':
    spec['operations'].extend(old)
elif variant == 'thin_cap':
    # One interior slab covers the entire slot with overlap in existing solid.
    # Unlike a box plus two cylinder unions it has no coincident cap joins.
    spec['operations'].append({'shape': 'box', 'size': [40., 8., .01], 'at': [0., -13., 2.715], 'op': 'union'})
elif variant == 'cross_tunnel':
    spec['operations'].append({'shape': 'box', 'size': [1., 28., .01], 'at': [0., 0., 2.705], 'op': 'difference'})
elif variant == 'local_dent':
    spec['operations'].append({'shape': 'cylinder', 'radius': 1., 'height': 2.,
        'at': [0., 0., 8.91], 'op': 'difference', 'vertices': 64})
obj = backend['build_csg'](spec)
if variant == 'thin_cap':
    # Boolean unions leave coincident/sliver vertices at box/circular joins.
    # Canonicalize the CONTROL mesh before both exports; keep the evaluator's
    # geometry tolerances unchanged and preserve the 10 micrometre membrane.
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    bmesh.ops.remove_doubles(mesh, verts=list(mesh.verts), dist=1e-8)
    bmesh.ops.triangulate(mesh, faces=list(mesh.faces), quad_method='BEAUTY', ngon_method='BEAUTY')
    mesh.to_mesh(obj.data)
    mesh.free()
    obj.data.update()
if variant == 'roughness_change':
    obj.data.materials[0].node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .15
elif variant == 'retriangulated':
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('Equivalent tessellation', 'TRIANGULATE')
    modifier.quad_method = 'FIXED_ALTERNATE'
    bpy.ops.object.modifier_apply(modifier=modifier.name)
elif variant not in {'nominal', 'wrong_width', 'wrong_depth', 'old_slots', 'thin_cap', 'cross_tunnel', 'local_dent'}:
    raise ValueError('Unknown public plate control')
obj.name = 'Editable geometry'
bpy.context.scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'), export_format='GLB', export_animations=False)
