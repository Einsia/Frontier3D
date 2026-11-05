"""Text2Code 003 public-instruction fixture, including a portable helper module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    args,
    blue,
    boolean,
    box,
    bpy,
    brass,
    cylinder,
    finish,
    ring,
    scene,
    silver,
)

finish(box((.170, .100, .006), (0, 0, .003)), 'Base', blue, (0, 0, -.025))
for side in (-1, 1):
    y = side*.030
    finish(cylinder(.004, .150, (0, y, .026), 'X'), f'Guide rod {side}', silver, (0, side*.09, 0))
    finish(ring(.009, .0042, .040, (0, y, .026), 'X'), f'Guide sleeve {side}', brass, (0, side*.055, .035))
    x = side*.076
    support = box((.012, .090, .036), (x, 0, .024))
    for hole_y, radius in ((-.030, .0042), (0, .0052), (.030, .0042)):
        boolean(support, cylinder(radius, .018, (x, hole_y, .026), 'X'))
    finish(support, f'End support {side}', blue, (side*.045, 0, .025))

finish(cylinder(.005, .182, (0, 0, .026), 'X'), 'Lead rod', silver, (0, -.15, 0))
nut = box((.024, .022, .018), (0, 0, .026))
boolean(nut, cylinder(.0052, .030, (0, 0, .026), 'X'))
finish(nut, 'Nut block', blue, (0, .075, .035))
finish(box((.058, .086, .006), (0, 0, .038)), 'Moving platform', blue, (0, 0, .090))
finish(ring(.018, .0052, .006, (.088, 0, .026), 'X'), 'Handwheel', blue, (.09, 0, .035))
scene.frame_start, scene.frame_end = 1, 61
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
