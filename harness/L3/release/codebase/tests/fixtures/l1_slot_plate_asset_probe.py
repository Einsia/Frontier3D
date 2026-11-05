"""Read-only native/GLB asset inspection for Code014 kernel development.

Private target assets are evaluator references, not candidate submissions.
This is not an orchestrator run or model/whole-task acceptance experiment.
"""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import bpy

PROJECT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--case', choices=('013', '014'), default='014')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True, exist_ok=False)
loader = importlib.util.spec_from_file_location('trusted_inspector', PROJECT/'src/evaluator/l1_blender.py')
inspector = importlib.util.module_from_spec(loader)
loader.loader.exec_module(inspector)
policy = inspector._mesh_kernel().GEOMETRY_POLICY
task = PROJECT/('data/3dbench/tasks/L1/CodeEdit/task_L1_CodeEdit_'+args.case)
rows = []
for label, relative in [('initial_native', 'environment/input/initial.blend'),
                        ('initial_glb', 'solution/reference/initial.glb'),
                        ('target_native', 'solution/reference/target.blend'),
                        ('target_glb', 'solution/reference/target.glb')]:
    source = task/relative
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source.suffix == '.blend':
        bpy.ops.wm.open_mainfile(filepath=str(source))
    else:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    bpy.context.scene.frame_set(1)
    folder = args.output/label
    folder.mkdir()
    facts, _ = inspector._collect(policy, mesh_dir=folder/'meshes')
    (folder/'facts.json').write_text(json.dumps(facts, indent=2, allow_nan=False)+'\n')
    assert source_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    meshes = [r for r in facts['objects'].values() if r.get('type') == 'MESH'
              and r.get('entity_scope') == 'delivery_geometry']
    rows.append({'label': label, 'asset_path': str(source.resolve()), 'asset_sha256': source_hash,
        'facts_path': str(folder/'facts.json'), 'facts_sha256': hashlib.sha256((folder/'facts.json').read_bytes()).hexdigest(),
        'valid': len(meshes) == 1 and meshes[0]['valid_solid'],
        'records': [{k: r.get(k) for k in ('valid_solid', 'closed', 'components', 'invalid_reasons',
                                         'vertices', 'faces', 'degenerate_faces')} for r in meshes]})
    (args.output/'results.json').write_text(json.dumps(rows, indent=2, allow_nan=False)+'\n')
    print(json.dumps(rows[-1]), flush=True)
