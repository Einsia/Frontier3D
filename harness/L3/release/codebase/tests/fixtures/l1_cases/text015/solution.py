"""Public-instruction coupling fixture; no hidden reference assets."""
import math
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import (
    args,
    blue,
    boolean,
    bpy,
    brass,
    cylinder,
    finish,
    ring,
    scene,
    silver,
)

for i,z in enumerate((0,.022)):
    hub=cylinder(.012,.018,(0,0,z))
    boolean(hub,cylinder(.027,.008,(0,0,z)),'UNION')
    boolean(hub,cylinder(.0082,.024,(0,0,z)))
    for j in range(3):
        a=j*2*math.pi/3
        boolean(hub,cylinder(.0032,.024,(.02*math.cos(a),.02*math.sin(a),z)))
    finish(hub,f'Coupling half {i}',blue,(0,0,(-1 if i==0 else 1)*.06))
for i,z in enumerate((-.021,.043)):
    finish(cylinder(.008,.024,(0,0,z)),f'Shaft {i}',silver,(0,0,(-1 if i==0 else 1)*.115))
finish(ring(.014,.0084,.003,(0,0,.011),'Z'),'Spacer',brass,(.09,0,0))
for i in range(3):
    a=i*2*math.pi/3
    x,y=.02*math.cos(a),.02*math.sin(a)
    finish(ring(.006,.0032,.0015,(x,y,.02675),'Z'),f'Washer {i}',brass,(x*2,y*2,.065))
    bolt=cylinder(.003,.03151,(x,y,.011755))
    boolean(bolt,cylinder(.0054,.004,(x,y,.0295),vertices=6),'UNION')
    finish(bolt,f'Bolt {i}',silver,(x*3,y*3,.100))
scene.frame_start,scene.frame_end=1,61
scene.frame_set(1)
args.output_dir.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'),export_format='GLB',export_animations=False)
