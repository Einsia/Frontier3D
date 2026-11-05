"""Retain pure EMPTY targets of camera/light TRACK_TO constraints unchanged."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

TRACKED_SHA256 = 'c6e0fa36e59c04b38b41aa52e00ebe6c74ce94f6c23f7c6f08f13750366bc38e'
LIGHT_SHA256 = '4281698777ce1421566d91bc3ce78f8616777888c6f05ab10a12a2dc8579b550'


def load(name, expected):
    path = Path(__file__).with_name(name+'.py')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Pinned environment dependency changed: '+name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dependency_graph(cameras, lights, original_dependencies):
    seeds = dict(cameras)
    for light in lights:
        for constraint in light.constraints:
            target = constraint.target if constraint.type == 'TRACK_TO' else None
            if target is None or target.type != 'EMPTY' or constraint.subtarget:
                raise ValueError('LIGHT dependency must be TRACK_TO to a pure EMPTY: '+light.name)
            seeds[target.name] = target
    # The pinned validator rejects geometry, instances, drivers, NLA and
    # unsupported constraints throughout every target's parent closure.
    return original_dependencies(seeds)


def build(request):
    import bpy
    tracked = load('tracked_camera_export_blender', TRACKED_SHA256)
    helper = load('light_tracked_camera_export_blender', LIGHT_SHA256)
    original_load = tracked.load_pinned
    original_dependencies = tracked.dependencies
    original_sample = tracked.sample
    light_names = set()
    states = []

    def dependencies(cameras):
        lights = [obj for obj in bpy.context.scene.objects if obj.type == 'LIGHT' and obj.constraints]
        graph = dependency_graph(cameras, lights, original_dependencies)
        for light in lights:
            helper.safe_light(light, graph)
        return graph

    def load_base(name, expected):
        module = original_load(name, expected)
        if name == 'continuous_image_export_blender':
            strict = module.check_static_object
            def check(obj):
                if obj.type == 'LIGHT' and obj.constraints:
                    cameras = {o.name:o for o in bpy.context.scene.objects if o.type == 'CAMERA'}
                    helper.safe_light(obj, dependencies(cameras))
                    light_names.add(obj.name)
                else:
                    strict(obj)
            module.check_static_object = check
        return module

    def sample(scene, objects, frames):
        result = original_sample(scene, objects, frames)
        full = {}
        for frame in frames:
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            full[str(frame)] = {}
            for name, obj in objects.items():
                if obj.type == 'LIGHT':
                    state = helper.light_state(obj)
                    full[str(frame)][name] = state
                    result[str(frame)][name]['light_state_sha256'] = hashlib.sha256(
                        json.dumps(state, sort_keys=True).encode()).hexdigest()
        states.append(full)
        return result

    tracked.load_pinned = load_base
    tracked.dependencies = dependencies
    tracked.sample = sample
    tracked.__file__ = __file__
    path = Path(request['output'])/'result.json'
    if path.exists():
        raise ValueError('Accepted environment dependency result must not be replaced')
    try:
        tracked.build(request)
        if not light_names or states[0] != states[1]:
            raise ValueError('Constrained light state not preserved across reload')
        result = json.loads(path.read_text())
        result['environment_dependency_validation'] = dict(
            tracked_worker_sha256=TRACKED_SHA256, light_worker_sha256=LIGHT_SHA256,
            lights=sorted(light_names), light_settings_before=states[0], light_settings_after=states[1],
            constraint_targets='pure_empty_camera_or_light_dependency_closure',
            animation_baked=False, full_light_state_preserved=True)
        path.write_text(json.dumps(result, indent=2))
    except Exception:
        if path.exists():
            path.unlink()
        raise


if __name__ == '__main__':
    build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
