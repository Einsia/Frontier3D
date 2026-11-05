"""Disposable Blender renders for the saved-camera L1 image protocol.

Loaded only as an evaluator-owned sibling by l1_blender.py. Never saves the
scene. Geometry masks replace shaders only AFTER the native beauty render.
"""
import hashlib
from pathlib import Path

import bpy
from mathutils import Vector

PROTOCOL = 'l1-saved-camera-v1'


def geometry_mask(scene, path):
    """Opaque evaluated-geometry mask, not inferred from background colours."""
    material = bpy.data.materials.new('__l1_geometry_mask')
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    shader = nodes.new('ShaderNodeEmission')
    shader.inputs['Color'].default_value = (1, 1, 1, 1)
    output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(shader.outputs[0], output.inputs['Surface'])
    for layer in scene.view_layers:
        layer.material_override = material
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.render.film_transparent = True
    scene.world = None
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file():
        raise RuntimeError('Blender did not write the geometry mask')
    return str(path)


def render_saved(view, directory):
    scene = bpy.context.scene
    scene.frame_set(view.get('frame', 1))
    render = scene.render
    if scene.camera is None:
        raise ValueError('Saved scene has no active camera')
    # Do not silently strip an unsupported image pipeline and call it faithful.
    compositor = getattr(scene, 'compositing_node_group', None) or getattr(scene, 'node_tree', None)
    if render.use_compositing and compositor is not None:
        raise ValueError('Saved-camera MVP does not yet support compositor output')
    sequence = scene.sequence_editor
    strips = getattr(sequence, 'strips', getattr(sequence, 'sequences', ())) if sequence else ()
    if render.use_sequencer and len(strips):
        raise ValueError('Saved-camera MVP does not yet support sequence editor output')
    if render.use_multiview or sum(layer.use for layer in scene.view_layers) != 1:
        raise ValueError('Saved-camera MVP requires one render view and one active view layer')
    if render.use_border or render.use_crop_to_border:
        raise ValueError('Saved-camera MVP requires a full uncropped render')
    width = render.resolution_x * render.resolution_percentage // 100
    height = render.resolution_y * render.resolution_percentage // 100
    if [width, height] != view['beauty_resolution']:
        raise ValueError('Saved render size differs from the declared image protocol')
    if render.engine not in {'CYCLES', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH'}:
        raise ValueError('Unsupported native render engine: ' + render.engine)
    metadata = {
        'render_protocol': PROTOCOL, 'beauty_backend': 'blender_native',
        'camera_source': 'saved', 'frame': scene.frame_current,
        'camera_matrix_world': [list(row) for row in scene.camera.matrix_world],
        'camera_type': scene.camera.data.type, 'resolution': [width, height],
        'engine': render.engine, 'view_transform': scene.view_settings.view_transform,
        'look': scene.view_settings.look, 'exposure': scene.view_settings.exposure,
        'gamma': scene.view_settings.gamma, 'cycles_samples': scene.cycles.samples,
        'cycles_seed': scene.cycles.seed, 'cycles_denoising': scene.cycles.use_denoising,
        'cycles_adaptive_sampling': scene.cycles.use_adaptive_sampling,
        'device_override': 'CPU' if render.engine == 'CYCLES' else None,
        'scope': 'Saved camera/materials/lights/world and sampling; no compositor or sequencer',
    }
    # Keep samples, seed, denoising, adaptive sampling, appearance and camera.
    # CPU avoids a dependency on a candidate's unavailable GPU configuration.
    if render.engine == 'CYCLES':
        scene.cycles.device = 'CPU'
    render.use_compositing = False
    render.use_sequencer = False
    render.image_settings.file_format = 'PNG'
    render.image_settings.color_mode = 'RGBA'
    render.image_settings.color_depth = '8'
    render.use_file_extension = True
    path = Path(directory) / f"{view['id']}_beauty.png"
    render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.is_file():
        raise RuntimeError('Blender did not write the saved-camera render')
    metadata['image'] = str(path)
    metadata['mask'] = geometry_mask(scene, Path(directory) / f"{view['id']}_geometry.png")
    metadata['mask_protocol'] = 'opaque-evaluated-geometry-alpha-v1'
    metadata['mask_sha256'] = hashlib.sha256(Path(metadata['mask']).read_bytes()).hexdigest()
    return metadata


def render_declared(view, directory):
    """Evaluator camera for tasks without a submitted-camera/PNG requirement.

Only camera and raster settings are declared here; scene materials, lights,
world, engine and sampling remain native. Never fit a camera to the candidate
or adopt its arbitrary camera/markers. The original blend is not saved.
"""
    scene = bpy.context.scene
    scene.frame_set(view['frame'])
    scale = scene.unit_settings.scale_length
    data = bpy.data.cameras.new('__l1_declared_camera')
    data.type = 'ORTHO'
    data.ortho_scale = view['ortho_scale']/scale
    data.clip_start, data.clip_end = 1e-5/scale, 1000/scale
    camera = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(camera)
    camera.location = Vector(view['location'])/scale
    direction = Vector(view['target'])/scale-camera.location
    camera.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    for marker in scene.timeline_markers:
        marker.camera = None
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = view['beauty_resolution']
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    # Full-frame output is evaluator-declared here, unlike a saved PNG check.
    scene.render.use_border = scene.render.use_crop_to_border = False
    result = render_saved(view, directory)
    result.update(render_protocol='l1-declared-camera-v1', camera_source='declared',
                  camera_definition={key: view[key] for key in ('location', 'target', 'ortho_scale')},
                  scope='Declared camera/native raster size; saved materials, lights, world, engine and sampling')
    return result
