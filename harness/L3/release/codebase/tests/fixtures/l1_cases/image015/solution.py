"""Public twin-rail dimensions and input-view arrangement; no private target."""
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

base = box((.160, .090, .006), (0, 0, .003))
carriage = box((.060, .074, .006), (0, 0, .036))
for x in (-.018, .018):
    for y in (-.025, .025):
        boolean(base, cylinder(.0032, .010, (x, y, .003)))
        boolean(carriage, cylinder(.0032, .010, (x, y, .036)))
        sleeve = ring(.009, .0052, .016, (x, y, .024), 'X')
        boolean(sleeve, cylinder(.0032, .012, (x, y, .030)))
        finish(sleeve, f'Bushing {x} {y}', brass, (x * 2, y * 2, .025))
        washer = ring(.006, .0032, .0015, (x, y, .03975), 'Z')
        finish(washer, f'Washer {x} {y}', brass, (x * 2, y * 2, .070))
        bolt = cylinder(.003, .00951, (x, y, .03575))
        boolean(bolt, cylinder(.0054, .004, (x, y, .0425), vertices=6), 'UNION')
        finish(bolt, f'Bolt {x} {y}', silver, (x * 2, y * 2, .100))
finish(base, 'Base', blue, (0, 0, -.025))
finish(carriage, 'Carriage', blue, (0, 0, .045))
for sign in (-1, 1):
    y = sign * .025
    finish(cylinder(.005, .144, (0, y, .024), 'X'), f'Rail {sign}', silver, (0, sign * .095, 0))
    x = sign * .070
    support = box((.012, .076, .028), (x, 0, .020))
    for side in (-1, 1):
        boolean(support, cylinder(.0052, .018, (x, side * .025, .024), 'X'))
    finish(support, f'Support {sign}', blue, (sign * .045, 0, .020))
scene.frame_start, scene.frame_end = 1, 61
scene.frame_set(1)
args.output_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
