"""Preserve self-contained camera actions in the pinned GLB inspection adapter.

No animation is removed or baked. Native meshes are still discarded by the
original adapter; camera transforms and optics are verified after reloading.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

BASE_SHA256 = 'd52ed83cf97f2de8f0a994fc9752d67d5b529b2a76582bb6dcab4be1e0d268f4'
OPTICS = ('lens', 'ortho_scale', 'shift_x', 'shift_y', 'sensor_width', 'sensor_height',
          'clip_start', 'clip_end')


def safe_camera(obj):
    if obj.parent or obj.constraints:
        raise ValueError('Camera parent or constraints require a separate adapter')
    for block in (obj, obj.data):
        animation = block.animation_data
        if animation and (animation.drivers or animation.nla_tracks):
            raise ValueError('Camera drivers or NLA require a separate adapter')
    if obj.data.dof.focus_object:
        raise ValueError('Camera focus depends on a native object')


def sample(scene, cameras, frames):
    import bpy
    result = {}
    for frame in frames:
        scene.frame_set(frame); bpy.context.view_layer.update()
        values = {}
        for name, obj in cameras.items():
            values[name] = {'matrix': [float(v) for row in obj.matrix_world for v in row],
                           'optics': [float(getattr(obj.data, key)) for key in OPTICS],
                           'type': obj.data.type, 'sensor_fit': obj.data.sensor_fit,
                           'focus_distance': float(obj.data.dof.focus_distance)}
        result[str(frame)] = values
    return result


def assert_same(before, after):
    if before.keys() != after.keys():
        raise ValueError('Camera sample population changed')
    for frame, cameras in before.items():
        if cameras.keys() != after[frame].keys():
            raise ValueError('Camera population changed')
        for name, expected in cameras.items():
            actual = after[frame][name]
            if expected['type'] != actual['type'] or expected['sensor_fit'] != actual['sensor_fit']:
                raise ValueError('Camera projection changed')
            for key in ('matrix', 'optics', 'focus_distance'):
                a = expected[key] if isinstance(expected[key], list) else [expected[key]]
                b = actual[key] if isinstance(actual[key], list) else [actual[key]]
                if len(a) != len(b) or any(not math.isfinite(x) or not math.isfinite(y)
                                          or abs(x-y) > 1e-6 for x, y in zip(a, b)):
                    raise ValueError('Camera animation changed: '+name+' frame '+frame+' '+key)


def build(request):
    import bpy
    base_path = Path(__file__).with_name('continuous_image_export_blender.py')
    if hashlib.sha256(base_path.read_bytes()).hexdigest() != BASE_SHA256:
        raise ValueError('Base export adapter changed')
    spec = importlib.util.spec_from_file_location('pinned_export_adapter', base_path)
    base = importlib.util.module_from_spec(spec); spec.loader.exec_module(base)
    native = request['native']
    if base.digest(native['path']) != native['sha256']:
        raise ValueError('Native source changed')
    bpy.ops.wm.open_mainfile(filepath=native['path'], load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    frames = sorted(set(range(scene.frame_start, scene.frame_end+1)) | {request['frame']})
    if not frames or len(frames) > 1000:
        raise ValueError('Camera verification frame range exceeds adapter limit')
    cameras = {o.name:o for o in scene.objects if o.type == 'CAMERA'}
    for obj in cameras.values():safe_camera(obj)
    before = sample(scene, cameras, frames)
    strict = base.check_static_object
    def check(obj):
        if obj.type == 'CAMERA':safe_camera(obj)
        else:strict(obj)
    base.check_static_object = check
    # Bind the result to this adapter, whose source pins the original dependency.
    base.__file__ = __file__
    base.build(request)
    output = Path(request['output']); result_path = output/'result.json'
    result = json.loads(result_path.read_text())
    bpy.ops.wm.open_mainfile(filepath=result['scene']['path'], load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    copies = {name:bpy.data.objects['__native_environment_'+name] for name in cameras}
    after = sample(scene, copies, frames)
    try:
        assert_same(before, after)
    except BaseException:
        result_path.rename(output/'unverified-result.json')
        raise
    result['camera_action_validation'] = {'frames': frames, 'cameras': sorted(cameras),
        'before': before, 'after': after, 'maximum_absolute_tolerance': 1e-6,
        'animation_preserved': True, 'base_worker_sha256': BASE_SHA256}
    result_path.write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
