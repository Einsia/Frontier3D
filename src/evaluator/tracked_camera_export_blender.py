"""Preserve camera TRACK_TO/EMPTY dependencies without baking native geometry."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

BASE_SHA256 = 'd52ed83cf97f2de8f0a994fc9752d67d5b529b2a76582bb6dcab4be1e0d268f4'
KEYFRAMED_SHA256 = '82172ad79963a59cc0ace7b209048988981fa411f16b3e731baeebc626704d5b'
OPTICS = ('lens','ortho_scale','shift_x','shift_y','sensor_width','sensor_height','clip_start','clip_end')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def load_pinned(name, expected):
    path=Path(__file__).with_name(name+'.py')
    if digest(path)!=expected:raise ValueError('Pinned export dependency changed: '+name)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def safe_dependency(obj):
    if obj.type not in {'CAMERA','EMPTY'} or obj.instance_type!='NONE' or obj.instance_collection:
        raise ValueError('Camera dependency must be a non-instanced camera or EMPTY: '+obj.name)
    if obj.type=='EMPTY' and obj.data is not None:raise ValueError('EMPTY contains native data')
    if obj.modifiers or obj.library or obj.parent_type!='OBJECT':
        raise ValueError('Unsupported camera dependency: '+obj.name)
    for block in (obj,obj.data):
        animation=getattr(block,'animation_data',None)
        if animation and (animation.drivers or animation.nla_tracks):
            raise ValueError('Camera dependency drivers or NLA unsupported: '+obj.name)
    if obj.type=='CAMERA' and obj.data.dof.focus_object:
        raise ValueError('Camera focus depends on a native object')
    for constraint in obj.constraints:
        if (obj.type!='CAMERA' or constraint.type!='TRACK_TO' or constraint.target is None
                or constraint.target.type!='EMPTY' or constraint.subtarget):
            raise ValueError('Only camera TRACK_TO to pure EMPTY is supported: '+obj.name)


def dependencies(cameras):
    result={};pending=list(cameras.values())
    while pending:
        obj=pending.pop()
        if obj.name in result:continue
        safe_dependency(obj);result[obj.name]=obj
        if obj.parent:pending.append(obj.parent)
        pending.extend(c.target for c in obj.constraints)
    return result


def sample(scene, objects, frames):
    import bpy
    values={}
    for frame in frames:
        scene.frame_set(frame);bpy.context.view_layer.update()
        values[str(frame)]={}
        for name,obj in objects.items():
            row=dict(matrix=[float(v) for r in obj.matrix_world for v in r])
            if obj.type=='CAMERA':
                row.update(optics=[float(getattr(obj.data,key)) for key in OPTICS],
                           type=obj.data.type,sensor_fit=obj.data.sensor_fit,
                           focus_distance=float(obj.data.dof.focus_distance))
            elif obj.type=='LIGHT':
                row.update(light_type=obj.data.type,energy=float(obj.data.energy),color=list(obj.data.color))
            values[str(frame)][name]=row
    return values


def assert_samples(before,after):
    if before.keys()!=after.keys():raise ValueError('Tracked frame population changed')
    for frame,objects in before.items():
        if objects.keys()!=after[frame].keys():raise ValueError('Tracked object population changed')
        for name,expected in objects.items():
            actual=after[frame][name]
            if expected.keys()!=actual.keys():raise ValueError('Tracked sample shape changed')
            for key,value in expected.items():
                other=actual[key]
                if isinstance(value,str):
                    if value!=other:raise ValueError('Tracked projection/type changed')
                else:
                    a=value if isinstance(value,list) else [value]
                    b=other if isinstance(other,list) else [other]
                    if len(a)!=len(b) or any(not math.isfinite(x) or not math.isfinite(y) or abs(x-y)>1e-6 for x,y in zip(a,b)):
                        raise ValueError('Tracked sample changed: '+name+' frame '+frame+' '+key)


def geometry(objects):
    result={}
    for obj in objects:
        if obj.type=='MESH':
            mesh=obj.data
            value=dict(vertices=[list(v.co) for v in mesh.vertices],polygons=[list(p.vertices) for p in mesh.polygons])
            result[obj.name]=hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()
    return result


def authored_state(obj, names=None):
    """Record authored actions, hierarchy and constraint settings without baking."""
    names=names or {}
    def animation(block):
        data=getattr(block,'animation_data',None)
        action=data.action if data else None
        if action is None:return None
        curves=[]
        curves.extend(getattr(action,'fcurves',[]))
        for layer in getattr(action,'layers',[]):
            for strip in layer.strips:
                for bag in getattr(strip,'channelbags',[]):curves.extend(bag.fcurves)
        return dict(name=action.name,slot=getattr(getattr(data,'action_slot',None),'identifier',None),
                    curves=[dict(path=f.data_path,index=f.array_index,extrapolation=f.extrapolation,
                                 keys=[dict(co=list(k.co),left=list(k.handle_left),right=list(k.handle_right),
                                            interpolation=k.interpolation,left_type=k.handle_left_type,right_type=k.handle_right_type)
                                       for k in f.keyframe_points]) for f in curves])
    constraints=[]
    for constraint in obj.constraints:
        settings={}
        for prop in constraint.bl_rna.properties:
            if prop.is_readonly or prop.identifier=='rna_type':continue
            value=getattr(constraint,prop.identifier)
            if prop.type in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:
                settings[prop.identifier]=list(value) if getattr(prop,'is_array',False) else value
        constraints.append(dict(type=constraint.type,target=names.get(constraint.target.name,constraint.target.name),settings=settings))
    return dict(parent=names.get(obj.parent.name,obj.parent.name) if obj.parent else None,
                parent_type=obj.parent_type,parent_inverse=[float(v) for row in obj.matrix_parent_inverse for v in row],
                object_action=animation(obj),data_action=animation(obj.data),constraints=constraints)


def build(request):
    import bpy
    base=load_pinned('continuous_image_export_blender',BASE_SHA256)
    load_pinned('keyframed_camera_export_blender',KEYFRAMED_SHA256)
    for source in (request['native'],request['export']):
        if digest(source['path'])!=source['sha256']:raise ValueError('Tracked source changed')
    bpy.ops.wm.open_mainfile(filepath=request['native']['path'],load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    frames=sorted(set(range(scene.frame_start,scene.frame_end+1))|{request['frame']})
    if not frames or len(frames)>1000:raise ValueError('Tracked frame range exceeds limit')
    scale=float(scene.unit_settings.scale_length)
    if not math.isfinite(scale) or scale<=0:raise ValueError('Invalid authored scene unit')
    if scene.world and (scene.world.animation_data or (scene.world.node_tree and scene.world.node_tree.animation_data)):
        raise ValueError('Animated native world unsupported')
    if scene.world and scene.world.node_tree and any(getattr(n,'object',None) for n in scene.world.node_tree.nodes):
        raise ValueError('Native world depends on a native object')
    cameras={o.name:o for o in scene.objects if o.type=='CAMERA'}
    if request['active_camera'] not in cameras:raise ValueError('Bound native camera differs')
    graph=dependencies(cameras)
    lights={o.name:o for o in scene.objects if o.type=='LIGHT'}
    for obj in lights.values():base.check_static_object(obj)
    tracked={**graph,**lights};before=sample(scene,tracked,frames)
    authored_before={name:authored_state(obj) for name,obj in tracked.items()}
    scene.frame_set(request['frame']);bpy.context.view_layer.update()
    originals=list(bpy.data.objects);copies={};records=[]
    action_records={}
    for name,obj in tracked.items():
        copied=obj.copy()
        if obj.data:copied.data=obj.data.copy()
        copied.name='__native_environment_'+name
        copies[name]=copied
        # Copy preserves actions/slots; originals are never edited or baked.
        action_records[name]=dict(object_action=obj.animation_data.action.name if obj.animation_data and obj.animation_data.action else None,
                                  data_action=obj.data.animation_data.action.name if obj.data and obj.data.animation_data and obj.data.animation_data.action else None)
        records.append(dict(native_name=name,type=obj.type,parent=obj.parent.name if obj.parent else None,
                            constraints=[dict(type=c.type,target=c.target.name) for c in obj.constraints],
                            matrix_world_native_units=[list(v) for v in obj.matrix_world],hide_render=obj.hide_render))
    for name,obj in tracked.items():
        copied=copies[name]
        if obj.parent:copied.parent=copies[obj.parent.name]
        for old,new in zip(obj.constraints,copied.constraints):new.target=copies[old.target.name]
    for obj in originals:bpy.data.objects.remove(obj,do_unlink=True)
    for other in list(bpy.data.scenes):
        if other!=scene:bpy.data.scenes.remove(other)
    for collection in list(bpy.data.collections):bpy.data.collections.remove(collection)
    for table in (bpy.data.meshes,bpy.data.curves,bpy.data.metaballs,bpy.data.armatures,bpy.data.materials,bpy.data.texts):
        for item in list(table):
            if item.users==0:table.remove(item)
    if bpy.data.meshes or any(o.type not in {'CAMERA','LIGHT','EMPTY'} for o in bpy.data.objects):
        raise ValueError('Native geometry survived environment isolation')
    for copied in copies.values():scene.collection.objects.link(copied)
    scene.camera=copies[request['active_camera']]
    for marker in scene.timeline_markers:marker.camera=None
    prior=set(bpy.data.objects)
    scene.unit_settings.scale_length=1;scene.render.fps=24;scene.render.fps_base=1
    bpy.ops.import_scene.gltf(filepath=request['export']['path'])
    imported=set(bpy.data.objects)-prior
    if not imported:raise ValueError('GLB contains no imported objects')
    mesh_sources=geometry(imported)
    if not mesh_sources:raise ValueError('GLB contains no mesh geometry')
    roots=[o for o in imported if o.parent not in imported]
    conversion=bpy.data.objects.new('__format_metres_to_native_units',None)
    scene.collection.objects.link(conversion);conversion.scale=(1/scale,)*3
    for obj in roots:obj.parent=conversion
    omitted=[]
    for obj in imported:
        if obj.type=='LIGHT':obj.hide_render=True;omitted.append(obj.name)
    scene.unit_settings.scale_length=scale;scene.camera=copies[request['active_camera']]
    scene.frame_set(request['frame']);bpy.context.view_layer.update()
    output=Path(request['output']);output.mkdir(parents=True,exist_ok=True);output.chmod(0o777)
    destination=output/'scene.blend'
    root_names=sorted(o.name for o in roots);imported_names=sorted(o.name for o in imported)
    bpy.ops.wm.save_as_mainfile(filepath=str(destination),check_existing=False)
    bpy.ops.wm.open_mainfile(filepath=str(destination),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    reloaded={name:bpy.data.objects['__native_environment_'+name] for name in tracked}
    after=sample(scene,reloaded,frames);assert_samples(before,after)
    name_map={obj.name:name for name,obj in reloaded.items()}
    authored_after={name:authored_state(obj,name_map) for name,obj in reloaded.items()}
    if authored_before!=authored_after:raise ValueError('Authored actions/hierarchy/constraints changed')
    if geometry(bpy.data.objects)!=mesh_sources:raise ValueError('GLB mesh population changed after reload')
    for source in (request['native'],request['export']):
        if digest(source['path'])!=source['sha256']:raise ValueError('Source modified during tracked inspection')
    result=dict(native=request['native'],export=request['export'],scene=dict(path=str(destination),sha256=digest(destination)),
        native_unit_scale_m=scale,root_scale=1/scale,import_fps=24,frame=request['frame'],environment=records,
        disabled_imported_lights=omitted,imported_roots=root_names,imported_objects=imported_names,
        registration='fixed_declared_unit_conversion_only',native_geometry_retained=False,
        lighting_policy='same_authored_native_lights_world_and_cameras_for_export_geometry_and_material_inspection',
        candidate_code_executed=False,source_unchanged=True,worker_sha256=digest(__file__),request_sha256=digest(request['request_path']),
        tracked_camera_validation=dict(frames=frames,cameras=sorted(cameras),dependencies=sorted(graph),before=before,after=after,
            maximum_absolute_tolerance=1e-6,animation_preserved=True,constraints_preserved=True,action_records=action_records,
            authored_before=authored_before,authored_after=authored_after,
            native_meshes_before_import=0,imported_mesh_sha256=mesh_sources,base_worker_sha256=BASE_SHA256,keyframed_worker_sha256=KEYFRAMED_SHA256))
    (output/'result.json').write_text(json.dumps(result,indent=2))


if __name__=='__main__':build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
