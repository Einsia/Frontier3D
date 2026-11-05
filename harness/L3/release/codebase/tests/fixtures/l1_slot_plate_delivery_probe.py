"""Inspector-owned read-only native/GLB facts for actual public controls."""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

import bpy

PROJECT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--submission', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True, exist_ok=False)
loader = importlib.util.spec_from_file_location('trusted_inspector', PROJECT/'src/evaluator/l1_blender.py')
inspector = importlib.util.module_from_spec(loader)
loader.loader.exec_module(inspector)
rows = []
for label, filename in [('native', 'scene.blend'), ('glb', 'scene.glb')]:
    if label == 'native':
        bpy.ops.wm.open_mainfile(filepath=str(args.submission/filename))
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(args.submission/filename))
    bpy.context.scene.frame_set(1)
    directory = args.output/label
    directory.mkdir()
    facts, _ = inspector._collect(inspector._mesh_kernel().GEOMETRY_POLICY, mesh_dir=directory/'meshes')
    (directory/'facts.json').write_text(json.dumps(facts, indent=2, allow_nan=False)+'\n')
    meshes = [r for r in facts['objects'].values() if r.get('type') == 'MESH' and r.get('entity_scope') == 'delivery_geometry']
    rows.append({'format': label, 'valid': len(meshes) == 1 and meshes[0]['valid_solid'],
        'objects': [{k: r.get(k) for k in ('valid_solid', 'invalid_reasons', 'closed', 'components', 'degenerate_faces')}
                    for r in meshes]})
(args.output/'summary.json').write_text(json.dumps(rows, indent=2)+'\n')
print(json.dumps(rows), flush=True)
