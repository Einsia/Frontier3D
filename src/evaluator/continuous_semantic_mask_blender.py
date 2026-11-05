"""Render reviewed geometry roles, retaining all unselected geometry as occluders."""
import json
from pathlib import Path
import sys


def render(scene, selected_objects, path):
    import bpy
    names = set(selected_objects)
    if len(names) != len(selected_objects): raise ValueError('Duplicate semantic object locator')
    for name in names:
        obj = scene.objects.get(name)
        if obj is None or obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
            raise ValueError('Reviewed geometry object is absent: '+name)
    for obj in scene.objects:
        value = 1. if obj.name in names else 0.
        obj.color = (value, value, value, 1.)
    material = bpy.data.materials.new('__continuous_semantic_geometry_mask')
    material.use_nodes = True; nodes = material.node_tree.nodes; nodes.clear()
    obj_info = nodes.new('ShaderNodeObjectInfo'); emission = nodes.new('ShaderNodeEmission')
    output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(obj_info.outputs['Color'], emission.inputs['Color'])
    material.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
    for layer in scene.view_layers: layer.material_override = material
    scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 1
    scene.cycles.seed = 0; scene.cycles.use_denoising = False; scene.cycles.use_adaptive_sampling = False
    scene.render.use_compositing = False; scene.render.use_sequencer = False
    scene.render.film_transparent = True; scene.world = None
    scene.view_settings.view_transform = 'Raw'; scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0.; scene.view_settings.gamma = 1.
    scene.render.image_settings.file_format = 'PNG'; scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'; scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not Path(path).is_file(): raise ValueError('Semantic mask render absent')


def main():
    import bpy
    sys.path.insert(0, str(Path(__file__).parent))
    from continuous_l2_silhouette_blender import sha, CAMERA_FIELDS
    request_path = Path(sys.argv[sys.argv.index('--')+1]); request = json.loads(request_path.read_text())
    root = Path(__file__).resolve().parents[2]
    for path, expected in request['implementation'].items():
        if sha(root/path) != expected: raise ValueError('Semantic mask implementation changed')
    source = request['scene']; source_path = Path(source['path'])
    if sha(source_path) != source['sha256']: raise ValueError('Retained source changed')
    bpy.ops.wm.open_mainfile(filepath=str(source_path), load_ui=False, use_scripts=False)
    scene = bpy.context.scene; scene.frame_set(request['frame'])
    camera = scene.objects.get(request['camera']['object'])
    if camera is None or camera.type != 'CAMERA': raise ValueError('Saved camera absent')
    record = {'object': camera.name, 'matrix_world': [list(v) for v in camera.matrix_world],
        'unit_scale': scene.unit_settings.scale_length,
        'settings': {k: getattr(camera.data, k) for k in CAMERA_FIELDS}}
    size = [scene.render.resolution_x*scene.render.resolution_percentage//100,
            scene.render.resolution_y*scene.render.resolution_percentage//100]
    if (record != request['camera'] or size != request['resolution']
            or camera.data.type not in ('PERSP', 'ORTHO') or scene.render.use_border
            or scene.render.use_crop_to_border or scene.render.use_multiview
            or sum(v.use for v in scene.view_layers) != 1
            or scene.render.pixel_aspect_x != scene.render.pixel_aspect_y):
        raise ValueError('Original saved camera and uncropped square-pixel grid required')
    scene.camera = camera; output = Path(request['mask']); output.parent.mkdir(parents=True, exist_ok=True)
    render(scene, request['selected_objects'], output)
    if sha(source_path) != source['sha256']: raise ValueError('Source changed during disposable render')
    result = {'scene': source, 'source_unchanged': True, 'camera': record, 'frame': request['frame'],
        'resolution': size, 'selected_objects': request['selected_objects'],
        'mask': {'path': str(output), 'sha256': sha(output)}, 'request_sha256': sha(request_path),
        'implementation': request['implementation'], 'candidate_code_executed': False,
        'scope': 'reviewed_geometry_with_all_other_opaque_geometry_as_occluders',
        'mask_protocol': 'linear_emission_object_color_v1', 'mask_channel': 'R', 'threshold_uint8': 128}
    Path(request['output']).write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__': main()
