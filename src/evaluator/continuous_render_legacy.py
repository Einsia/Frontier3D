"""Read-only, evaluator-authored fixed-camera evidence (Blender worker)."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    import bpy
    from mathutils import Vector, Matrix
    sys.path.insert(0, str(Path(__file__).parent))
    from l1_image_blender import geometry_mask
    request = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text())
    source = Path(request['scene'])
    if sha(source) != request['scene_sha256']:
        raise ValueError('Source scene changed')
    results = {}
    for view in request['views']:
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        scene = bpy.context.scene
        scene.frame_set(view.get('frame', 1))
        scale = scene.unit_settings.scale_length
        for marker in scene.timeline_markers:
            marker.camera = None
        if view.get('camera'):
            camera = view['camera']
            data = bpy.data.cameras.new('__continuous_fixed_camera')
            data.type = camera.get('type', 'ORTHO')
            data.ortho_scale = camera['ortho_scale'] / scale
            data.clip_start, data.clip_end = .000001 / scale, 1000 / scale
            obj = bpy.data.objects.new(data.name, data)
            scene.collection.objects.link(obj)
            if 'matrix_world' in camera:
                obj.matrix_world = Matrix(camera['matrix_world'])
                obj.location /= scale
            else:
                obj.location = Vector(camera.get('position', camera.get('location'))) / scale
                if 'rotation' in camera:
                    obj.rotation_euler = camera['rotation']
                else:
                    obj.rotation_euler = (Vector(camera['target']) / scale - obj.location).to_track_quat('-Z', 'Y').to_euler()
            scene.camera = obj
        if scene.camera is None:
            raise ValueError('Missing saved or frozen camera')
        if view.get('studio'):
            for obj in list(scene.objects):
                if obj.type == 'LIGHT': bpy.data.objects.remove(obj, do_unlink=True)
            world = bpy.data.worlds.new('__continuous_studio')
            world.use_nodes = True
            world.node_tree.nodes['Background'].inputs[0].default_value = (.5, .5, .5, 1)
            world.node_tree.nodes['Background'].inputs[1].default_value = .8
            scene.world = world
            light = bpy.data.lights.new('__continuous_sun', 'SUN'); light.energy = 2
            obj = bpy.data.objects.new(light.name, light); scene.collection.objects.link(obj)
            obj.rotation_euler = (.4, -.5, -.4)
            scene.view_settings.view_transform = 'AgX'; scene.view_settings.exposure = 0
        scene.render.resolution_x, scene.render.resolution_y = view['resolution']
        scene.render.resolution_percentage = 100
        scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
        scene.render.use_border = scene.render.use_crop_to_border = scene.render.use_multiview = False
        scene.render.threads_mode = 'FIXED'; scene.render.threads = 2
        scene.render.use_compositing = scene.render.use_sequencer = False
        scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'
        scene.cycles.samples = 32; scene.cycles.seed = 20261016
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_mode = 'RGBA'
        record = {'frame': scene.frame_current, 'camera_matrix_world': [list(v) for v in scene.camera.matrix_world],
                  'resolution': view['resolution'], 'camera_policy': 'fixed_or_original_saved_no_candidate_fit',
                  'appearance': 'neutral_studio' if view.get('studio') else 'authored_material_lights_world_32_sample_rerender'}
        if view.get('image'):
            path = Path(view['image']); path.parent.mkdir(parents=True, exist_ok=True)
            scene.render.filepath = str(path); bpy.ops.render.render(write_still=True)
            record['image'] = {'path': str(path), 'sha256': sha(path)}
        if view.get('mask'):
            path = Path(view['mask']); path.parent.mkdir(parents=True, exist_ok=True)
            geometry_mask(scene, path)
            record['mask'] = {'path': str(path), 'sha256': sha(path)}
        results[view['id']] = record
    if sha(source) != request['scene_sha256']:
        raise ValueError('Worker modified source')
    Path(request['result']).write_text(json.dumps({'scene_sha256': request['scene_sha256'],
        'worker_sha256': sha(__file__), 'source_unchanged': True, 'autoexec': False, 'views': results}, indent=2))


if __name__ == '__main__':
    main()
