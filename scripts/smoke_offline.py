"""Render and export a synthetic scene through the real Docker/Blender runtime.

This diagnostic uses no task assets or model services. It verifies runtime
installation and native/GLB/image delivery; it does not produce benchmark scores.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orchestrator.runtime import blender_command, run_process

SCENE = '''import argparse,json,sys
from pathlib import Path
import bpy
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--input-dir');p.add_argument('--output-dir',type=Path);a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2)
obj=bpy.context.object;obj.name='Synthetic diagnostic cube'
bpy.ops.object.camera_add(location=(5,-6,4));camera=bpy.context.object;camera.rotation_euler=(Vector((0,0,0))-camera.location).to_track_quat('-Z','Y').to_euler()
scene=bpy.context.scene;scene.camera=camera
bpy.ops.object.light_add(type='AREA',location=(3,-4,6));bpy.context.object.data.energy=1000
scene.world=bpy.data.worlds.new('Diagnostic world');scene.world.color=(.1,.1,.1)
scene.render.engine='CYCLES';scene.cycles.samples=8
scene.render.resolution_x=128;scene.render.resolution_y=128;scene.render.resolution_percentage=100
out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(out/'scene.glb'),export_format='GLB')
scene.render.filepath=str(out/'render.png');bpy.ops.render.render(write_still=True)
(out/'inspection.json').write_text(json.dumps({'mesh_count':sum(x.type=='MESH' for x in scene.objects),'cube_dimensions':list(obj.dimensions)}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', default='3dbench-l1-blender:mvp')
    args = parser.parse_args()
    workspace = args.output.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    (workspace/'input').mkdir()
    (workspace/'output').mkdir()
    (workspace/'output/solution.py').write_text(SCENE)
    command, container = blender_command(workspace, args.blender.resolve(),
        runtime='docker', image=args.image, seed=0)
    record = run_process(command, cwd=workspace, directory=workspace/'process',
        deadline=time.monotonic()+300, timeout=300, container=container)
    if record['status'] != 'success':
        raise RuntimeError('Blender runtime failed; inspect '+str(workspace/'process'))
    output = workspace/'output'
    for name in ['scene.blend', 'scene.glb', 'render.png']:
        if not (output/name).is_file() or not (output/name).stat().st_size:
            raise RuntimeError('Missing diagnostic delivery: '+name)
    inspection = json.loads((output/'inspection.json').read_text())
    if inspection != {'mesh_count': 1, 'cube_dimensions': [2.0, 2.0, 2.0]}:
        raise RuntimeError('Synthetic native geometry check failed')
    if not (output/'render.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('Rendered image is not PNG')
    print('Offline Docker/Blender render/export smoke passed: '+str(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
