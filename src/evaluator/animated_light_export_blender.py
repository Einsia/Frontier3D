"""Preserve isolated light actions with strict keyframed cameras, without baking."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

TRACKED_SHA256='c6e0fa36e59c04b38b41aa52e00ebe6c74ce94f6c23f7c6f08f13750366bc38e'
LIGHT_STATE_SHA256='4281698777ce1421566d91bc3ce78f8616777888c6f05ab10a12a2dc8579b550'
OBJECT_PATHS={'location','rotation_euler','rotation_quaternion','rotation_axis_angle','scale',
              'delta_location','delta_rotation_euler','delta_rotation_quaternion','delta_scale'}
DATA_PATHS={'energy','color','size','size_y','shadow_soft_size','spot_size','spot_blend'}


def load(name,expected):
    path=Path(__file__).with_name(name+'.py')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Pinned animated-light dependency changed: '+name)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def safe_animation(block,allowed):
    animation=getattr(block,'animation_data',None)
    if not animation:return False
    if animation.drivers or animation.nla_tracks:raise ValueError('Animated LIGHT drivers or NLA unsupported')
    action=animation.action
    if not action:return False
    curves=list(getattr(action,'fcurves',[]))
    for layer in getattr(action,'layers',[]):
        for strip in layer.strips:
            for bag in getattr(strip,'channelbags',[]):
                if bag.slot_handle==animation.action_slot_handle:curves.extend(bag.fcurves)
    if not curves:raise ValueError('Animated LIGHT action has no bound curves')
    for curve in curves:
        if curve.data_path not in allowed or curve.modifiers:
            raise ValueError('Unsupported animated LIGHT action channel: '+curve.data_path)
    return True


def safe_light(obj):
    if (obj.type!='LIGHT' or obj.parent or obj.constraints or obj.modifiers or obj.library
            or obj.instance_type!='NONE' or obj.instance_collection):
        raise ValueError('Animated LIGHT must have no parent, constraints or instances: '+obj.name)
    animated=safe_animation(obj,OBJECT_PATHS)
    animated=safe_animation(obj.data,DATA_PATHS) or animated
    tree=obj.data.node_tree
    if tree:
        if tree.animation_data:raise ValueError('Animated LIGHT nodes unsupported')
        if any(n.bl_idname not in {'ShaderNodeEmission','ShaderNodeOutputLight'} for n in tree.nodes):
            raise ValueError('Unsupported animated LIGHT shader node')
        for node in tree.nodes:
            for prop in node.bl_rna.properties:
                if prop.type=='POINTER' and prop.identifier!='rna_type':
                    value=getattr(node,prop.identifier)
                    if getattr(value,'type',None) in {'MESH','EMPTY','CAMERA','LIGHT'}:
                        raise ValueError('Animated LIGHT node references an object')
    return animated


def build(request):
    import bpy
    tracked=load('tracked_camera_export_blender',TRACKED_SHA256)
    state_helper=load('light_tracked_camera_export_blender',LIGHT_STATE_SHA256)
    original_load=tracked.load_pinned;original_sample=tracked.sample;original_dependencies=tracked.dependencies
    animated_names=set();states=[]
    def load_base(name,expected):
        module=original_load(name,expected)
        if name=='continuous_image_export_blender':
            strict=module.check_static_object
            def check(obj):
                if obj.type=='LIGHT' and (obj.animation_data or obj.data.animation_data):
                    if safe_light(obj):animated_names.add(obj.name)
                else:strict(obj)
            module.check_static_object=check
        return module
    def dependencies(cameras):
        camera_worker=original_load('keyframed_camera_export_blender',tracked.KEYFRAMED_SHA256)
        for camera in cameras.values():camera_worker.safe_camera(camera)
        return original_dependencies(cameras)
    def sample(scene,objects,frames):
        result=original_sample(scene,objects,frames);full={}
        for frame in frames:
            scene.frame_set(frame);bpy.context.view_layer.update();full[str(frame)]={}
            for name,obj in objects.items():
                if obj.type=='LIGHT':
                    state=state_helper.light_state(obj);full[str(frame)][name]=state
                    result[str(frame)][name]['light_state_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
        states.append(full)
        return result
    tracked.load_pinned=load_base;tracked.dependencies=dependencies;tracked.sample=sample;tracked.__file__=__file__
    output=Path(request['output']);result_path=output/'result.json'
    if result_path.exists():raise ValueError('Accepted animated-light result must not be replaced')
    # Publish no successful receipt until all additional checks pass.
    try:
        tracked.build(request)
        if not animated_names:raise ValueError('Animated-light extension requires an animated LIGHT')
        if states[0]!=states[1]:raise ValueError('Animated LIGHT properties/nodes changed after reload')
        result=json.loads(result_path.read_text())
        result['animated_light_validation']=dict(tracked_worker_sha256=TRACKED_SHA256,
            light_state_worker_sha256=LIGHT_STATE_SHA256,base_worker_sha256=tracked.BASE_SHA256,
            keyframed_worker_sha256=tracked.KEYFRAMED_SHA256,lights=sorted(animated_names),
            light_settings_before=states[0],light_settings_after=states[1],
            full_light_state_preserved=True,nodes_and_socket_defaults_preserved=True,animation_baked=False,
            constraint_policy='no_light_parent_constraints_drivers_nla',camera_policy='strict_keyframed')
        result_path.write_text(json.dumps(result,indent=2))
    except Exception:
        if result_path.exists():result_path.unlink()
        raise


if __name__=='__main__':build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
