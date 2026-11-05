"""Build an export inspection scene using the submission's fixed native environment.

GLB geometry/materials remain imported by Blender's standard glTF importer.
Only the declared scene-unit conversion is applied to imported root objects.
No candidate/reference fitting or native geometry is allowed in the output.
"""
import hashlib
import json
import math
from pathlib import Path
import sys


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_static_object(obj):
    """Unsupported animated environment stays missing rather than being flattened."""
    current = obj
    while current is not None:
        if current.animation_data or current.constraints:
            raise ValueError('Animated/constrained native environment requires explicit baking: '+obj.name)
        current = current.parent
    if obj.data.animation_data:
        raise ValueError('Animated native environment data requires explicit baking: '+obj.name)
    if getattr(obj.data, 'node_tree', None) and obj.data.node_tree.animation_data:
        raise ValueError('Animated native light nodes require explicit baking: '+obj.name)


def build(request):
    import bpy
    native, exported = request['native'], request['export']
    for item in (native, exported):
        if digest(item['path']) != item['sha256']: raise ValueError('Retained image source changed')
    bpy.ops.wm.open_mainfile(filepath=native['path'], load_ui=False, use_scripts=False)
    scene = bpy.context.scene; scene.frame_set(request['frame']); bpy.context.view_layer.update()
    scale = float(scene.unit_settings.scale_length)
    if not math.isfinite(scale) or scale <= 0: raise ValueError('Invalid authored scene unit')
    if scene.world and (scene.world.animation_data or (scene.world.node_tree and scene.world.node_tree.animation_data)):
        raise ValueError('Animated native world requires explicit baking')
    if scene.world and scene.world.node_tree:
        for node in scene.world.node_tree.nodes:
            if getattr(node, 'object', None) is not None:
                raise ValueError('Native world depends on a native object')
    camera = scene.camera
    if camera is None: raise ValueError('Native primary camera missing')
    environment = []; originals = list(bpy.data.objects)
    for obj in list(scene.objects):
        if obj.type not in {'CAMERA', 'LIGHT'}: continue
        check_static_object(obj)
        copy = obj.copy(); copy.data = obj.data.copy()
        matrix = obj.matrix_world.copy(); copy.parent = None; copy.matrix_world = matrix
        copy.name = '__native_environment_'+obj.name
        environment.append((obj, copy, {'native_name': obj.name, 'type': obj.type,
            'matrix_world_native_units': [list(v) for v in matrix], 'hide_render': obj.hide_render}))
    for obj in originals: bpy.data.objects.remove(obj, do_unlink=True)
    # Remove source geometry even from unused scenes/data blocks exposed to the judge.
    for other in list(bpy.data.scenes):
        if other != scene: bpy.data.scenes.remove(other)
    for collection in list(bpy.data.collections): bpy.data.collections.remove(collection)
    for table in (bpy.data.meshes, bpy.data.curves, bpy.data.metaballs, bpy.data.armatures,
                  bpy.data.materials, bpy.data.texts):
        for item in list(table):
            if item.users == 0: table.remove(item)
    active_camera_name = None
    for old, obj, record in environment:
        scene.collection.objects.link(obj)
        # old RNA objects are removed above; identity was captured before removal.
        if record.get('active_camera'): scene.camera = obj
    # Locate the primary camera using the copied entry, without a geometry-derived fit.
    camera_records = [obj for _, obj, record in environment if record['type'] == 'CAMERA'
                      and record['native_name'] == request['active_camera']]
    if len(camera_records) != 1: raise ValueError('Bound native active camera differs')
    scene.camera = camera_records[0]; active_camera_name = scene.camera.name
    for marker in scene.timeline_markers: marker.camera = None
    before = set(bpy.data.objects)
    # Match the empty-scene importer used by the raw GLB inspector, including fps.
    scene.unit_settings.scale_length = 1
    scene.render.fps = 24; scene.render.fps_base = 1
    bpy.ops.import_scene.gltf(filepath=exported['path'])
    imported = set(bpy.data.objects)-before
    if not imported: raise ValueError('GLB contains no imported objects')
    roots = [obj for obj in imported if obj.parent not in imported]
    conversion = bpy.data.objects.new('__format_metres_to_native_units', None)
    scene.collection.objects.link(conversion); conversion.scale = (1/scale,)*3
    for obj in roots: obj.parent = conversion
    omitted_lights = []
    for obj in imported:
        if obj.type == 'LIGHT':
            obj.hide_render = True; omitted_lights.append(obj.name)
    scene.unit_settings.scale_length = scale
    scene.camera = bpy.data.objects[active_camera_name]
    scene.frame_set(request['frame']); bpy.context.view_layer.update()
    output = Path(request['output']); output.mkdir(parents=True, exist_ok=True)
    destination = output/'scene.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(destination), check_existing=False)
    for item in (native, exported):
        if digest(item['path']) != item['sha256']: raise ValueError('Source modified during export inspection')
    result = {'native': native, 'export': exported, 'scene': {'path': str(destination), 'sha256': digest(destination)},
        'native_unit_scale_m': scale, 'root_scale': 1/scale, 'import_fps': 24, 'frame': request['frame'],
        'environment': [record for _, _, record in environment], 'disabled_imported_lights': omitted_lights,
        'imported_roots': sorted(o.name for o in roots), 'imported_objects': sorted(o.name for o in imported),
        'registration': 'fixed_declared_unit_conversion_only', 'native_geometry_retained': False,
        'lighting_policy': 'same_authored_native_lights_world_and_cameras_for_export_geometry_and_material_inspection',
        'candidate_code_executed': False, 'source_unchanged': True,
        'worker_sha256': digest(__file__), 'request_sha256': digest(request['request_path'])}
    (output/'result.json').write_text(json.dumps(result, indent=2))


if __name__ == '__main__':
    build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
