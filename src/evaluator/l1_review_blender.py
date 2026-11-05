"""Collect compact native evidence for L1 evaluation.

No submitted Python or embedded scripts are executed. Full evaluated surfaces
are stored as binary NPZ, never expanded to hundreds of MB of JSON. Images are
disposable; the submitted scene is never saved or modified on disk.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name+'.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def studio_camera(scene, bounds, azimuth, elevation):
    low, high = (Vector(v) for v in bounds)
    center, radius = (low+high)/2, max((high-low).length, .001)
    az, el = math.radians(azimuth), math.radians(elevation)
    direction = Vector((math.cos(el)*math.cos(az), math.cos(el)*math.sin(az), math.sin(el)))
    data = bpy.data.cameras.new('L1ReviewCamera')
    data.type, data.ortho_scale = 'ORTHO', radius*1.1
    data.clip_start, data.clip_end = radius/10000, radius*1000
    camera = bpy.data.objects.new('L1ReviewCamera', data)
    scene.collection.objects.link(camera)
    camera.location = center+direction*radius*3
    camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera = camera
    for marker in scene.timeline_markers:
        marker.camera = None
    return camera


def main():
    request = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    source, output = Path(request['scene']), Path(request['output'])
    before = digest(source)
    if before != request['scene_sha256']:
        raise ValueError('Unbound scene')
    output.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower()=='.glb':
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    # Resolve the loaded native state before initializing numerical helpers.
    # A separate saved-camera worker uses the same initialization order.
    scene.frame_set(request.get('frame', scene.frame_current))
    global np
    import numpy as np
    if request.get('render_only'):
        geometry_path = output/'geometry.json'
        if digest(geometry_path) != request.get('geometry_receipt_sha256'):
            raise ValueError('Unbound geometry receipt before isolated render')
        result = json.loads(geometry_path.read_text())
        scale = float(scene.unit_settings.scale_length)
        if (result.get('scene_sha256') != before or result.get('frame') != request['frame']
                or result.get('unit_scale') != scale or result.get('renders') != {}
                or result.get('source_unchanged') is not True):
            raise ValueError('Geometry receipt belongs to another native scene or frame')
        for obj in result['objects']:
            path = Path(obj['path'])
            if not path.resolve().is_relative_to(output.resolve()) or digest(path) != obj['sha256']:
                raise ValueError('Retained geometry changed before isolated render')
        # The render operator owns render-graph evaluation; avoid constructing
        # an extra viewport dependency graph in this rendering-only process.
        scene.frame_set(request['frame'])
        result['render_isolation'] = 'fresh_process_same_immutable_asset'
        result['geometry_receipt'] = {'path':str(geometry_path), 'sha256':digest(geometry_path)}
        render_result(scene, request, source, output, before, result, result['bounds_m'], scale)
        return
    if request.get('material_frames'):
        # Preserve order and the repeated return frame in ONE opened scene.
        # This is a material-dependency audit, not an animation-shape score.
        snapshots=[]
        for index,frame in enumerate(request['material_frames']):
            scene.frame_set(frame);bpy.context.view_layer.update()
            graph=bpy.context.evaluated_depsgraph_get()
            audit=module('l1_procedural_materials').MaterialAudit();names=[]
            for instance in graph.object_instances:
                obj=instance.object
                if obj.type not in {'MESH','CURVE','SURFACE','FONT','META'} or obj.hide_render:continue
                mesh=obj.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
                try:
                    if mesh is None or not len(mesh.polygons):continue
                    names.append(obj.original.name)
                    effective=[obj.material_slots[i].material if i<len(obj.material_slots) and obj.material_slots[i].link=='OBJECT' else mat for i,mat in enumerate(mesh.materials)]
                    override=bpy.context.view_layer.material_override
                    audit.materials([override] if override else effective,{0} if override else {p.material_index for p in mesh.polygons},'object:'+obj.original.name)
                finally:obj.to_mesh_clear()
            audit.scene(scene,names,bpy.context.view_layer)
            snapshots.append({'index':index,'frame':frame,'observed_frame':scene.frame_current,
                              'audit':audit.result(frame=scene.frame_current)})
        if digest(source)!=before:raise ValueError('Scene changed during material sequence')
        (output/'sequence.json').write_text(json.dumps({'method':'l1-compact-material-sequence-v1',
            'source_sha256':before,'frames':request['material_frames'],'autoexec_enabled':False,
            'source_unchanged':True,'snapshots':snapshots},ensure_ascii=False,indent=2))
        return
    scene.frame_set(request['frame'])
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    scale = float(scene.unit_settings.scale_length)
    objects, lows, highs, render_names = [], [], [], []
    audit = module('l1_procedural_materials').MaterialAudit()
    total = 0
    real_geometry = False
    for instance in graph.object_instances:
        obj = instance.object
        if obj.type not in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'} or obj.hide_render:
            continue
        mesh = obj.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
        try:
            if mesh is None or not len(mesh.polygons):
                continue
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
            if total > 12_000_000:
                raise ValueError('Complete geometry exceeds 12 million triangle review capacity')
            vertices = np.empty(len(mesh.vertices)*3, dtype=np.float64)
            mesh.vertices.foreach_get('co', vertices)
            vertices = vertices.reshape(-1,3)
            matrix = np.asarray(instance.matrix_world, dtype=np.float64)
            vertices = (vertices@matrix[:3,:3].T+matrix[:3,3])*scale
            centered = vertices-vertices.mean(0)
            eigenvalues = np.linalg.eigvalsh(centered.T@centered/max(1,len(centered)))
            real_geometry |= bool(eigenvalues[0] > max(1e-20,eigenvalues[-1]*1e-10))
            faces = np.empty(len(mesh.loop_triangles)*3, dtype=np.int32)
            mesh.loop_triangles.foreach_get('vertices', faces)
            faces = faces.reshape(-1,3)
            path = output/f'geometry-{len(objects):05d}.npz'
            np.savez_compressed(path, vertices=vertices, triangles=faces)
            low, high = vertices.min(0), vertices.max(0)
            lows.append(low); highs.append(high); render_names.append(obj.original.name)
            effective = [obj.material_slots[i].material if i < len(obj.material_slots)
                         and obj.material_slots[i].link == 'OBJECT' else mat
                         for i, mat in enumerate(mesh.materials)]
            override = bpy.context.view_layer.material_override
            audit.materials([override] if override else effective,
                            {0} if override else {p.material_index for p in mesh.polygons},
                            'object:'+obj.original.name)
            objects.append({'object': obj.original.name, 'instance': bool(instance.is_instance),
                            'path': str(path), 'sha256': digest(path), 'triangles': len(faces),
                            'bounds_m': [low.tolist(),high.tolist()]})
        finally:
            obj.to_mesh_clear()
    if not objects:
        raise ValueError('No complete visible surface')
    audit.scene(scene, render_names, bpy.context.view_layer)
    bounds = [np.min(lows,axis=0).tolist(),np.max(highs,axis=0).tolist()]
    result = {'method': 'l1-compact-native-review-v1', 'scene_sha256': before,
              'frame': request['frame'], 'unit_scale': scale, 'bounds_m': bounds,
              'objects': objects, 'triangles': total, 'material_audit': audit.result(frame=request['frame']),
              'has_real_geometry': real_geometry,
              'active_camera': scene.camera.name if scene.camera else None,
              'source_unchanged': digest(source) == before, 'renders': {}}
    if request.get('geometry_only'):
        if digest(source)!=before:
            raise ValueError('Source changed during collection')
        (output/'native.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return
    # Evaluated to_mesh()/to_mesh_clear() traversal can leave Blender's Cycles
    # acceleration structures stale on some scenes. Reopen the same immutable
    # asset before rendering, so the render consumes a fresh dependency graph.
    # Retained geometry/material observations above remain bound to these bytes.
    if digest(source) != before:
        raise ValueError('Source changed before render isolation')
    if source.suffix.lower() == '.glb':
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    scene.frame_set(request['frame'])
    bpy.context.view_layer.update()
    if float(scene.unit_settings.scale_length) != scale:
        raise ValueError('Scene units changed across render isolation')
    result['render_isolation'] = 'reopen_same_immutable_asset_after_geometry_collection'
    render_result(scene, request, source, output, before, result, bounds, scale)


def render_result(scene, request, source, output, before, result, bounds, scale):
    # Text prompts never required a camera or lights. Use the SAME documented
    # studio presentation for every Text candidate; do not reward judge lighting.
    if request.get('studio'):
        for obj in list(scene.objects):
            if obj.type == 'LIGHT':
                bpy.data.objects.remove(obj, do_unlink=True)
        world = bpy.data.worlds.new('L1ReviewStudio')
        world.use_nodes = True
        world.node_tree.nodes['Background'].inputs[0].default_value = (.5,.5,.5,1)
        world.node_tree.nodes['Background'].inputs[1].default_value = .8
        scene.world = world
        data = bpy.data.lights.new('L1ReviewSun', 'SUN'); data.energy = 2
        obj = bpy.data.objects.new(data.name, data); scene.collection.objects.link(obj)
        obj.rotation_euler = (.4,-.5,-.4)
        scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 32
        scene.cycles.seed = 0
        scene.view_settings.view_transform = 'AgX'; scene.view_settings.exposure = 0
    if request.get('main_required'):
        if request.get('studio'):
            studio_camera(scene, (np.asarray(bounds)/scale).tolist(), -50, 30)
            scene.render.resolution_x = scene.render.resolution_y = 768
            scene.render.resolution_percentage = 100
        if scene.camera is None:
            raise ValueError('Required authored camera missing')
        render = scene.render
        if render.use_border or render.use_crop_to_border or render.use_multiview:
            raise ValueError('Unsupported render framing')
        if getattr(scene, 'compositing_node_group', None) and render.use_compositing:
            raise ValueError('Composited pipeline requires separate audit')
        render.use_compositing = render.use_sequencer = False
        if render.engine == 'CYCLES':
            scene.cycles.device = 'CPU'
        render.image_settings.file_format = 'PNG'; render.image_settings.color_mode = 'RGBA'
        render.filepath = str(output/'main.png')
        bpy.ops.render.render(write_still=True)
        result['renders']['main'] = {'path': str(output/'main.png'), 'sha256': digest(output/'main.png'),
                                     'studio': bool(request.get('studio')), 'frame': scene.frame_current}
    # Always supply an independent reverse view, not a renamed copy of main.
    studio_camera(scene, (np.asarray(bounds)/scale).tolist(), 130, 30)
    scene.render.engine = 'CYCLES'; scene.cycles.device = 'CPU'; scene.cycles.samples = 16
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.use_compositing = scene.render.use_sequencer = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(output/'alternate.png')
    bpy.ops.render.render(write_still=True)
    result['renders']['alternate'] = {'path': str(output/'alternate.png'), 'sha256': digest(output/'alternate.png'),
                                     'diagnostic_camera': True, 'frame': scene.frame_current}
    if digest(source) != before:
        raise ValueError('Source changed during collection')
    (output/'native.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
