"""Extend one pinned tracked-camera adapter to strictly scoped tracked lights."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

TRACKED_SHA256='c6e0fa36e59c04b38b41aa52e00ebe6c74ce94f6c23f7c6f08f13750366bc38e'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def safe_light(obj,graph):
    if (obj.type!='LIGHT' or obj.parent or obj.instance_type!='NONE' or obj.instance_collection
            or obj.library or obj.modifiers):raise ValueError('Unsupported tracked LIGHT structure: '+obj.name)
    for block in (obj,obj.data):
        animation=getattr(block,'animation_data',None)
        if animation and (animation.drivers or animation.nla_tracks):
            raise ValueError('Tracked LIGHT drivers or NLA unsupported: '+obj.name)
    if not obj.constraints:raise ValueError('Tracked LIGHT extension requires a TRACK_TO constraint')
    for constraint in obj.constraints:
        target=constraint.target if constraint.type=='TRACK_TO' else None
        if (target is None or target.type!='EMPTY' or graph.get(target.name) is not target or constraint.subtarget):
            raise ValueError('Tracked LIGHT target must be a pure camera-closure EMPTY: '+obj.name)
    tree=obj.data.node_tree
    if tree:
        if tree.animation_data:raise ValueError('Animated LIGHT nodes unsupported: '+obj.name)
        for node in tree.nodes:
            if node.bl_idname not in {'ShaderNodeEmission','ShaderNodeOutputLight'}:
                raise ValueError('Unsupported LIGHT shader node: '+node.bl_idname)
            for prop in node.bl_rna.properties:
                if prop.type=='POINTER' and prop.identifier!='rna_type':
                    value=getattr(node,prop.identifier)
                    if getattr(value,'type',None) in {'MESH','EMPTY','CAMERA','LIGHT'}:
                        raise ValueError('LIGHT shader node references an object')


def scalar_properties(block,excluded=()):
    result={}
    for prop in block.bl_rna.properties:
        if prop.identifier in {'rna_type','name','name_full',*excluded} or prop.is_readonly:continue
        if prop.type not in {'BOOLEAN','INT','FLOAT','STRING','ENUM'}:continue
        value=getattr(block,prop.identifier)
        if getattr(prop,'is_array',False):value=list(value)
        elif isinstance(value,set):value=sorted(value)
        result[prop.identifier]=value
    return result


def light_state(obj):
    """Preserve light data, visibility, nodes, socket defaults and links exactly."""
    data=obj.data;tree=data.node_tree
    state=dict(data=scalar_properties(data),object=scalar_properties(obj,{'location','rotation_euler','rotation_quaternion','scale','delta_location','delta_rotation_euler','delta_rotation_quaternion','delta_scale','matrix_world','matrix_local','matrix_basis','matrix_parent_inverse'}))
    # Engine settings are nested RNA groups rather than top-level light data.
    for owner,label in [(obj,'object'),(data,'data')]:
        groups={}
        for prop in owner.bl_rna.properties:
            if prop.type!='POINTER' or prop.identifier in {'rna_type','id_data','data','parent','node_tree','animation_data'}:continue
            value=getattr(owner,prop.identifier,None)
            if value is not None and hasattr(value,'bl_rna') and not hasattr(value,'users'):
                values=scalar_properties(value)
                if values:groups[prop.identifier]=values
        state[label+'_groups']=groups
    if tree:
        state['nodes']=[dict(name=n.name,type=n.bl_idname,properties=scalar_properties(n),
            inputs=[dict(identifier=s.identifier,properties=scalar_properties(s)) for s in n.inputs],
            outputs=[dict(identifier=s.identifier,properties=scalar_properties(s)) for s in n.outputs]) for n in tree.nodes]
        state['links']=sorted((l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in tree.links)
    else:state.update(nodes=[],links=[])
    return state


def build(request):
    import bpy
    path=Path(__file__).with_name('tracked_camera_export_blender.py')
    if digest(path)!=TRACKED_SHA256:raise ValueError('Pinned tracked-camera worker changed')
    spec=importlib.util.spec_from_file_location('pinned_tracked_camera',path)
    tracked=importlib.util.module_from_spec(spec);spec.loader.exec_module(tracked)
    original_load=tracked.load_pinned;original_sample=tracked.sample;light_names=set();light_states=[]
    def load(name,expected):
        module=original_load(name,expected)
        if name=='continuous_image_export_blender':
            strict=module.check_static_object
            def check(obj):
                if obj.type=='LIGHT' and obj.constraints:
                    cameras={o.name:o for o in bpy.context.scene.objects if o.type=='CAMERA'}
                    graph=tracked.dependencies(cameras)
                    safe_light(obj,graph);light_names.add(obj.name)
                else:strict(obj)
            module.check_static_object=check
        return module
    def sample(scene,objects,frames):
        result=original_sample(scene,objects,frames)
        first_frame={}
        for frame in frames:
            scene.frame_set(frame);bpy.context.view_layer.update()
            for name,obj in objects.items():
                if obj.type=='LIGHT':
                    state=light_state(obj)
                    if frame==frames[0]:first_frame[name]=state
                    result[str(frame)][name]['light_state_sha256']=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
        light_states.append(first_frame)
        return result
    tracked.load_pinned=load;tracked.sample=sample
    # The pinned implementation uses __file__ only to locate its same-directory
    # dependencies and bind the resulting worker digest. Bind this wrapper.
    tracked.__file__=__file__
    result_path=Path(request['output'])/'result.json'
    if result_path.exists():raise ValueError('Accepted light-tracked result must not be replaced')
    tracked.build(request)
    result=json.loads(result_path.read_text())
    result['light_tracked_validation']=dict(tracked_worker_sha256=TRACKED_SHA256,
        base_worker_sha256=tracked.BASE_SHA256,keyframed_worker_sha256=tracked.KEYFRAMED_SHA256,
        lights=sorted(light_names),full_light_state_preserved=True,nodes_and_socket_defaults_preserved=True,
        light_settings_before=light_states[0],light_settings_after=light_states[1],
        constraint_targets='pure_empty_in_camera_dependency_closure',animation_baked=False)
    result_path.write_text(json.dumps(result,indent=2))


if __name__=='__main__':build(json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text()))
