"""Public roller dimensions and visible arrangement, including actual main.png."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    args,
    boolean,
    box,
    bpy,
    brass,
    cylinder,
    finish,
    material,
    ring,
    scene,
    silver,
)
from mathutils import Vector

teal = material('Teal', (.08, .32, .38))
orange = material('Orange roller', (.65, .24, .08))
dark = material('Dark gray handwheel', (.08, .11, .14))
base = box((.180, .100, .008), (0, 0, .004))
for sign in (-1, 1):
    x = sign * .058
    support = box((.016, .076, .056), (x, 0, .036))
    boolean(support, cylinder(.0162, .022, (x, 0, .044), 'X'))
    for side in (-1, 1):
        y = side * .028
        boolean(base, cylinder(.0032, .012, (x, y, .004)))
        boolean(support, cylinder(.0032, .060, (x, y, .036)))
        washer = ring(.006, .0032, .0015, (x, y, .06475), 'Z')
        finish(washer, f'Washer {sign} {side}', brass, (sign * .04, side * .04, .06))
        bolt = cylinder(.003, .06001, (x, y, .0355))
        boolean(bolt, cylinder(.0054, .004, (x, y, .0675), vertices=6), 'UNION')
        finish(bolt, f'Bolt {sign} {side}', silver, (sign * .06, side * .07, .11))
    finish(support, f'Support {sign}', teal, (sign * .055, 0, .020))
    finish(ring(.016, .0102, .016, (x, 0, .044), 'X'), f'Sleeve {sign}', brass, (sign * .03, .07, .03))
    finish(ring(.016, .0102, .008, (sign * .071, 0, .044), 'X'), f'Collar {sign}', brass, (sign * .035, -.07, .025))
finish(base, 'Base', teal, (0, 0, -.025))
finish(cylinder(.010, .184, (0, 0, .044), 'X'), 'Shaft', silver, (0, -.13, 0))
finish(ring(.025, .0102, .064, (0, 0, .044), 'X'), 'Roller', orange, (0, 0, .085))
wheel = ring(.030, .0102, .008, (.086, 0, .044), 'X')
for i in range(3):
    angle = i * 2 * math.pi / 3
    boolean(wheel, cylinder(.006, .014, (.086, .020 * math.cos(angle), .044 + .020 * math.sin(angle)), 'X'))
finish(wheel, 'Handwheel', dark, (.11, 0, .02))
scene.frame_start, scene.frame_end = 1, 61
scene.frame_set(1)
scene.world = bpy.data.worlds.new('Neutral studio')
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.7, .7, .7, 1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value = .7
bpy.ops.object.camera_add(location=(.26, -.36, .24))
camera = bpy.context.object
camera.rotation_euler = (Vector((0, 0, .035)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
camera.data.type = 'ORTHO'
camera.data.ortho_scale = .28
camera.data.clip_start = .0001
scene.camera = camera
for x, y, energy in [(-.16, -.18, 10), (.20, .15, 5)]:
    bpy.ops.object.light_add(type='AREA', location=(x, y, .35))
    light = bpy.context.object
    light.data.energy = energy
    light.data.size = .25
    light.rotation_euler = (Vector((0, 0, .04)) - light.location).to_track_quat('-Z', 'Y').to_euler()
scene.render.engine = 'CYCLES'
scene.cycles.samples = 16
scene.cycles.use_denoising = False
scene.render.resolution_x, scene.render.resolution_y = 1440, 1080
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.view_settings.view_transform = 'AgX'
args.output_dir.mkdir(parents=True, exist_ok=True)
scene.render.filepath = str(args.output_dir / 'main.png')
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir / 'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir / 'scene.glb'), export_format='GLB', export_animations=False)
bpy.ops.render.render(write_still=True)
