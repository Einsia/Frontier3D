"""Preflight public washer fixture topology in real native/GLB inspections."""
import argparse
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import bpy

project = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.mkdir(parents=True, exist_ok=False)
loader = importlib.util.spec_from_file_location('trusted_inspector', project/'src/evaluator/l1_blender.py')
inspector = importlib.util.module_from_spec(loader)
loader.loader.exec_module(inspector)
policy = inspector._mesh_kernel().GEOMETRY_POLICY
source = (project/'tests/fixtures/l1_washer_fixture.py').read_text()
rows = []
for variant in ('wrong_radius', 'local_dent', 'thin_cap', 'index_hole_damage'):
    folder = args.output/variant
    folder.mkdir()
    (folder/'solution.py').write_text(source)
    (folder/'control.json').write_text(json.dumps({'variant': variant}))
    sys.argv = ['solution.py', '--', '--input-dir',
                str(project/'data/3dbench/tasks/L1/CodeEdit/task_L1_CodeEdit_015/environment/input'),
                '--output-dir', str(folder)]
    runpy.run_path(str(folder/'solution.py'), run_name='__main__')
    for kind in ('native', 'glb'):
        if kind == 'glb':
            bpy.ops.wm.read_factory_settings(use_empty=True)
            bpy.ops.import_scene.gltf(filepath=str(folder/'scene.glb'))
        facts, _ = inspector._collect(policy)
        records = [r for r in facts['objects'].values() if r.get('type') == 'MESH']
        rows.append({'variant': variant, 'format': kind,
                     'valid': len(records) == 1 and records[0]['valid_solid'],
                     'records': [{k: r.get(k) for k in ('valid_solid', 'closed', 'components', 'invalid_reasons',
                                                       'vertices', 'faces', 'degenerate_faces')} for r in records]})
    (args.output/'results.json').write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(rows[-2:]), flush=True)
