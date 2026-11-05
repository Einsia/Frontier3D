"""Read inherited scene properties, including hidden data and shader outputs.

All candidate code stays disabled. Geometry is exported in its original local
coordinates with its observed world matrix; no fitting or registration occurs.
"""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
from l2_case_blender import properties,references,modifier_inputs,tree_signature,render_settings,normalize,driver_signatures
from continuous_mesh_data_blender import attributes


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def pointer(path):return {'path':str(path),'sha256':digest(path)}


def tree(tree_data,seen=None):
    if tree_data is None:return None
    seen=set() if seen is None else seen
    if tree_data.name in seen:return {'cycle':tree_data.name}
    result=tree_signature(tree_data)
    for node in tree_data.nodes:
        row=result['nodes'][node.name];outputs=[]
        for socket in node.outputs:
            value=getattr(socket,'default_value',None)
            if hasattr(value,'bl_rna'):value=getattr(value,'name',None)
            elif value is not None and not isinstance(value,(str,int,float,bool)):value=list(value)
            outputs.append([socket.identifier,normalize(value)])
        row['outputs']=outputs
        if getattr(node,'node_tree',None):row['group']=tree(node.node_tree,seen|{tree_data.name})
    return result


def complete_references(value):
    result=references(value)
    for name,item in result.items():
        dependency=getattr(value,name,None)
        if isinstance(dependency,bpy.types.NodeTree):item['nodes']=tree(dependency)
    return result


def inspect(request,folder):
    source=Path(request['scene']['path'])
    if digest(source)!=request['scene']['sha256']:raise ValueError('Source hash differs')
    bpy.ops.wm.open_mainfile(filepath=str(source),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    objects=[];materials={};meshes={};unit=float(scene.unit_settings.scale_length)
    for i,obj in enumerate(scene.objects):
        data=obj.data;slots=[]
        for slot in obj.material_slots:
            material=slot.material;slots.append(None if material is None else material.name)
            if material and material.name not in materials:
                materials[material.name]={'settings':properties(material),'nodes':tree(material.node_tree)}
        row={'object':obj.name,'type':obj.type,'parent':obj.parent.name if obj.parent else None,
            'parent_type':obj.parent_type,'parent_bone':obj.parent_bone,
            'collections':sorted(c.name for c in obj.users_collection),'matrix_world':np.asarray(obj.matrix_world).tolist(),
            'visibility':{k:getattr(obj,k) for k in ('hide_render','hide_viewport','visible_camera','visible_diffuse',
                'visible_glossy','visible_transmission','visible_volume_scatter','visible_shadow')},
            'materials':slots,'editable':obj.library is None and getattr(data,'library',None) is None,
            'modifiers':[{'settings':properties(m),'references':complete_references(m),'inputs':modifier_inputs(m)} for m in obj.modifiers],
            'constraints':[{'settings':properties(c),'references':complete_references(c)} for c in obj.constraints],
            'particles':[{'name':p.name,'seed':p.seed,'settings':properties(p.settings),'references':complete_references(p.settings)} for p in obj.particle_systems],
            'vertex_groups':[{'name':g.name,'index':g.index,'lock_weight':g.lock_weight} for g in obj.vertex_groups],
            'mesh':None,'data_settings':properties(data) if data is not None else None}
        if obj.type=='MESH':
            if data.name not in meshes:
                data.calc_loop_triangles();v=np.empty((len(data.vertices),3),dtype=np.float64)
                data.vertices.foreach_get('co',v.reshape(-1));f=np.empty((len(data.loop_triangles),3),dtype=np.int64)
                data.loop_triangles.foreach_get('vertices',f.reshape(-1));mi=np.empty(len(data.polygons),dtype=np.int32)
                data.polygons.foreach_get('material_index',mi);smooth=np.empty(len(data.polygons),dtype=bool)
                data.polygons.foreach_get('use_smooth',smooth)
                values={'vertices':v,'triangles':f,'material_indices':mi,'smooth':smooth}
                for j,uv in enumerate(data.uv_layers):
                    array=np.empty((len(uv.data),2),dtype=np.float64);uv.data.foreach_get('uv',array.reshape(-1));values['uv_'+str(j)]=array
                if data.shape_keys:
                    for j,key in enumerate(data.shape_keys.key_blocks):
                        array=np.empty((len(key.data),3),dtype=np.float64);key.data.foreach_get('co',array.reshape(-1));values['shape_'+str(j)]=array
                extra,metadata=attributes(data);values.update(extra)
                path=folder/('native-mesh-'+str(len(meshes))+'.npz');np.savez_compressed(path,**values)
                meshes[data.name]={'payload':pointer(path),'uv_layers':[u.name for u in data.uv_layers],'attributes':metadata,
                    'shape_keys':[] if data.shape_keys is None else [{'name':k.name,'value':k.value,'relative_key':k.relative_key.name,'settings':properties(k)}
                        for k in data.shape_keys.key_blocks]}
            row['mesh']=meshes[data.name]
        if obj.type in {'LIGHT','CAMERA'}:
            row['settings']=properties(data)
            if obj.type=='LIGHT':row['nodes']=tree(data.node_tree)
            else:row['dof']=properties(data.dof)
        if obj.type=='ARMATURE':
            row['rig']={'bones':{b.name:{'properties':properties(b),'head':list(b.head_local),'tail':list(b.tail_local)} for b in data.bones},
                'pose':{b.name:{'properties':properties(b),'matrix':np.asarray(b.matrix).tolist(),
                    'constraints':[{'settings':properties(c),'references':references(c)} for c in b.constraints]} for b in obj.pose.bones}}
        if obj.type in {'CURVE','SURFACE','FONT'} and hasattr(data,'splines'):
            row['splines']=[{'properties':properties(s),'points':[properties(p) for p in s.points],
                            'bezier':[properties(p) for p in s.bezier_points]} for s in data.splines]
        objects.append(row)
    world=scene.world
    ids=[item for p in bpy.data.bl_rna.properties if p.type=='COLLECTION' for item in getattr(bpy.data,p.identifier)]
    trees=[v.node_tree for v in ids if getattr(v,'node_tree',None)]+list(bpy.data.node_groups)
    render=render_settings(scene)
    render['compositor']=tree(scene.compositing_node_group) if hasattr(scene,'compositing_node_group') else tree(getattr(scene,'node_tree',None))
    result={'scene':request['scene'],'unit_scale':unit,'saved_frame':scene.frame_current,
        'active_camera':scene.camera.name if scene.camera else None,'objects':objects,'materials':materials,
        'world':None if world is None else {'settings':properties(world),'nodes':tree(world.node_tree)},
        'render':render,'drivers':driver_signatures(ids+trees),'geometry_space':'unchanged local coordinates',
        'includes_hidden_objects':True,'candidate_code_executed':False}
    if digest(source)!=request['scene']['sha256']:raise ValueError('Source mutated during inspection')
    return normalize(result)


if __name__=='__main__':
    request_path=Path(sys.argv[sys.argv.index('--')+1]);request=json.loads(request_path.read_text())
    folder=Path(request['output']);folder.mkdir(parents=True,exist_ok=True)
    result=inspect(request,folder)
    (folder/'result.json').write_text(json.dumps({'request_sha256':digest(request_path),'result':result},allow_nan=False)+'\n')
