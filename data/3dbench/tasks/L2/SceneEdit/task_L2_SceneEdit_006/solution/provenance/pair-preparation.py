import bpy,sys,json,hashlib
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from cc0_author_cases import CASES
R=Path(__file__).resolve().parents[1]
def val(x):
 try:v=x.default_value;return list(v) if hasattr(v,'__iter__') and not isinstance(v,str) else v
 except:return None
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def snapshot():
 s=bpy.context.scene;objs={}
 for o in s.objects:
  data={'type':o.type,'matrix':[list(v) for v in o.matrix_world],'hidden':o.hide_render}
  if o.type=='MESH':
   m=o.data;a=np.empty(len(m.vertices)*3,dtype=np.float32);m.vertices.foreach_get('co',a);b=np.empty(len(m.loops),dtype=np.int32);m.loops.foreach_get('vertex_index',b)
   data.update(mesh=hashlib.sha256(a.tobytes()+b.tobytes()).hexdigest(),materials=[m.name if m else None for m in o.data.materials])
  if o.type=='EMPTY':data['instance_collection']=o.instance_collection.name if o.instance_collection else None
  if o.type=='LIGHT':data.update(light_type=o.data.type,size=getattr(o.data,'size',None))
  objs[o.name]=data
 mats={}
 for m in bpy.data.materials:
  if not m.users:continue
  nt=m.node_tree
  mats[m.name]=digest({'nodes':[(n.name,n.bl_idname,[(i.identifier,val(i)) for i in n.inputs]) for n in nt.nodes] if nt else [],'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in nt.links] if nt else [],'diffuse':list(m.diffuse_color)})
 return {'objects':objs,'materials':mats,'camera':{'matrix':[list(v) for v in s.camera.matrix_world],'lens':s.camera.data.lens},'settings':{'frame':s.frame_current,'engine':s.render.engine,'resolution':[s.render.resolution_x,s.render.resolution_y],'view':s.view_settings.view_transform,'exposure':s.view_settings.exposure}}
key=sys.argv[-1];c=next(c for c in CASES if c['key']==key);base=R/'assets/cc0-replacements-20260921'/key;out=base/'pair';out.mkdir(exist_ok=True)
bpy.ops.wm.open_mainfile(filepath=str(base/'prepared/scene.blend'),use_scripts=False);s=bpy.context.scene;bpy.context.preferences.filepaths.save_version=0
for t in list(bpy.data.texts):bpy.data.texts.remove(t)
s.render.threads_mode='FIXED';s.render.threads=8;s.cycles.samples=12;s.cycles.use_denoising=True;s.render.image_settings.media_type='IMAGE';s.render.image_settings.file_format='PNG';s.render.use_compositing=False;s.render.use_sequencer=False
bpy.ops.file.pack_all();bpy.context.view_layer.update();before=snapshot()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'reference.blend'),compress=True);s.render.filepath=str(out/'reference.png');bpy.ops.render.render(write_still=True)
changes=[];removed=c.get('remove',[])
for name in removed:
 assert name in s.objects,name
 bpy.data.objects.remove(s.objects[name],do_unlink=True)
if c['mode']=='lighting':
 for light in bpy.data.lights:
  changes.append({'type':'light','name':light.name,'energy':light.energy,'color':list(light.color)});light.energy*=.2;light.color=(.12,.25,1)
 if key=='winter-castle' and s.world and s.world.node_tree:
  for n in s.world.node_tree.nodes:
   if n.type=='BACKGROUND':changes.append({'type':'world','node':n.name,'strength':n.inputs['Strength'].default_value});n.inputs['Strength'].default_value*=.18
bpy.data.orphans_purge(do_recursive=True);bpy.context.view_layer.update();after=snapshot()
assert set(after['objects'])==set(before['objects'])-set(removed)
assert all(v==before['objects'][k] for k,v in after['objects'].items())
assert all(v==before['materials'][k] for k,v in after['materials'].items())
assert before['camera']==after['camera'] and before['settings']==after['settings']
assert not bpy.data.libraries
assert all(im.packed_file for im in bpy.data.images if im.users and im.source=='FILE')
assert removed or changes
bpy.ops.wm.save_as_mainfile(filepath=str(out/'initial.blend'),compress=True);s.render.filepath=str(out/'initial.png');bpy.ops.render.render(write_still=True)
report={'key':key,'scope':'Data preparation validation, not model performance','target_objects_removed':removed,'private_original_values':changes,'preserved_objects_equal':True,'preserved_mesh_count':sum(v['type']=='MESH' for v in after['objects'].values()),'preserved_materials_equal':True,'camera_and_render_settings_equal':True,'packed_dependencies':True,'external_libraries':0,'settings':after['settings']}
(out/'pair-audit.json').write_text(json.dumps(report,indent=2));(out/'preserved-baseline.json').write_text(json.dumps(after,indent=2));print('VALIDATED_PAIR',key,flush=True)
