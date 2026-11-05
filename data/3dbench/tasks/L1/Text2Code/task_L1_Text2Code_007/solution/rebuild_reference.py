"""Private reference builder; never mount this file or reference/spec.json to an agent."""
import bpy,sys,json,argparse
from pathlib import Path
from mathutils import Vector
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'authoring'))
from build_assemblies import construct,camera_setup,render,inspect
args=argparse.ArgumentParser();args.add_argument('--output-dir',required=True)
options=args.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(options.output_dir).resolve();out.mkdir(parents=True,exist_ok=True)
spec=json.loads((HERE/'reference/spec.json').read_text(encoding='utf-8'))
construct(spec);scene,cam=camera_setup();geometry,checks,probes=inspect(spec);assert all(x['passed'] for x in checks)
for p in spec['parts']:
 o=bpy.data.objects[p['id']];o.location=Vector(p['at'])*.001;o.keyframe_insert('location',frame=1);o.location=(Vector(p['at'])+Vector(p['explode']))*.001;o.keyframe_insert('location',frame=61)
scene.frame_end=61;scene.frame_set(1);render(scene,cam,out/'assembled.png');cam.data.ortho_scale*=1.3;scene.render.filepath=str(out/'assembled.png');bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'));bpy.ops.export_scene.gltf(filepath=str(out/'scene.glb'),export_format='GLB',export_animations=False)
(out/'qa.json').write_text(json.dumps(checks,indent=2));print('PRIVATE_REFERENCE_REBUILT',spec['family'],len(checks),flush=True)
