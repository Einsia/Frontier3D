"""Read-only, bounded evidence of malformed evaluated native mesh indices."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import bpy


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    request_path = Path(sys.argv[sys.argv.index('--')+1])
    request = json.loads(request_path.read_text())
    scene = request['scene']
    if digest(scene['path']) != scene['sha256']:
        raise ValueError('Native audit source changed')
    bpy.ops.wm.open_mainfile(filepath=scene['path'], load_ui=False, use_scripts=False)
    bpy.context.scene.frame_set(request['frame'])
    validator_path = Path(__file__).with_name('l1_mesh_indices.py')
    spec = importlib.util.spec_from_file_location('_l1_mesh_indices', validator_path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    graph = bpy.context.evaluated_depsgraph_get()
    invalid = []
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or obj.hide_render:
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        try:
            if mesh is None:
                raise ValueError('Native mesh conversion unavailable')
            problem = validator.invalid_reference(mesh)
            if problem is not None:
                invalid.append(dict(object=obj.name, invalid=problem))
        finally:
            evaluated.to_mesh_clear()
    if digest(scene['path']) != scene['sha256']:
        raise ValueError('Native audit modified source')
    result = dict(protocol='native-mesh-index-audit-v1', scene=scene, frame=request['frame'],
                  invalid_meshes=invalid, source_unchanged=True, candidate_code_executed=False,
                  worker_sha256=digest(__file__), validator_sha256=digest(validator_path),
                  request_sha256=digest(request_path))
    Path(request['output']).write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
