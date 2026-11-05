"""Prepare real full/modified scene pairs and check all non-target scene data."""
import bpy,json,hashlib,sys,colorsys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'assets/expansion/artist_edits';bpy.context.preferences.filepaths.save_version=0
KEYS=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ['living-room','bistro','party_tug','autumn_forest']
def values(socket):
 try:v=socket.default_value;return list(v) if hasattr(v,'__iter__') and not isinstance(v,str) else v
 except:return None
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def snapshot():
 objects={}
 for o in bpy.context.scene.objects:
  if o.type=='MESH':
   m=o.data;a=np.empty(len(m.vertices)*3,dtype=np.float32);m.vertices.foreach_get('co',a);b=np.empty(len(m.loops),dtype=np.int32);m.loops.foreach_get('vertex_index',b)
   objects[o.name]={'mesh':hashlib.sha256(a.tobytes()+b.tobytes()).hexdigest(),'matrix':[list(v) for v in o.matrix_world],'materials':[m.name if m else None for m in o.data.materials],'hidden':o.hide_render}
 mats={}
 for m in bpy.data.materials:
  if not m.users:continue
  nodes=[]
  if m.node_tree:
   for n in m.node_tree.nodes:
    row={'name':n.name,'type':n.bl_idname,'inputs':[(p.identifier,values(p)) for p in n.inputs]}
    if n.bl_idname=='ShaderNodeValToRGB':row['ramp']=[(e.position,list(e.color)) for e in n.color_ramp.elements]
    nodes.append(row)
  mats[m.name]=digest({'diffuse':list(m.diffuse_color),'nodes':nodes,'links':[(l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in m.node_tree.links] if m.node_tree else []})
 s=bpy.context.scene;cam=s.camera
 return {'objects':objects,'materials':mats,'camera':{'matrix':[list(v) for v in cam.matrix_world],'lens':cam.data.lens},'settings':{'frame':s.frame_current,'engine':s.render.engine,'resolution':[s.render.resolution_x,s.render.resolution_y,s.render.resolution_percentage],'view':s.view_settings.view_transform,'look':s.view_settings.look,'exposure':s.view_settings.exposure}}
for key in KEYS:
 out=BASE/key;out.mkdir(parents=True,exist_ok=True);bank='interiors' if key=='living-room' else 'diverse';src=ROOT/'assets'/bank/key/'blender/scene.blend'
 bpy.ops.wm.open_mainfile(filepath=str(src),use_scripts=False,load_ui=False);s=bpy.context.scene
 if key=='bistro':s.view_settings.exposure=.7
 if s.render.engine=='CYCLES':s.cycles.samples=32;s.cycles.use_denoising=True
 for text in list(bpy.data.texts):bpy.data.texts.remove(text)
 bpy.ops.file.pack_all();bpy.context.view_layer.update();before=snapshot();bpy.ops.wm.save_as_mainfile(filepath=str(out/'reference.blend'))
 s.render.filepath=str(out/'reference.png');bpy.ops.render.render(write_still=True)
 changes=[];removed=[];allowed_materials=[]
 if key=='living-room':
  removed=[o.name for o in s.objects if o.name.startswith('TableWood_') or o.name in ['Glass_0001','Glass_0002','Glass_0003','BottleCap']]
 elif key=='bistro':removed=[o.name for o in s.objects if any('StreetPivot_'+str(i).zfill(3)+'_' in o.name for i in range(38,45))]
 elif key=='party_tug':
  for light in bpy.data.lights:
   changes.append({'type':'light','name':light.name,'energy':light.energy,'color':list(light.color)});light.energy*=.25;light.color=(.1,.3,1)
  for n in s.world.node_tree.nodes:
   if n.bl_idname=='ShaderNodeBackground':changes.append({'type':'world','name':n.name,'strength':n.inputs['Strength'].default_value});n.inputs['Strength'].default_value*=.4
 elif key=='autumn_forest':
  allowed_materials=['canopy','grass','grass2']
  for name in allowed_materials:
   for n in bpy.data.materials[name].node_tree.nodes:
    if n.bl_idname!='ShaderNodeValToRGB':continue
    for i,e in enumerate(n.color_ramp.elements):
     color=list(e.color);h,sat,v=colorsys.rgb_to_hsv(*color[:3])
     if sat>.35:
      changes.append({'type':'ramp_color','material':name,'node':n.name,'index':i,'color':color});e.color=(*colorsys.hsv_to_rgb(.32,sat,v),color[3])
 for name in removed:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
 bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=True,do_recursive=True);bpy.context.view_layer.update();after=snapshot()
 assert set(after['objects'])==set(before['objects'])-set(removed)
 assert all(v==before['objects'][k] for k,v in after['objects'].items())
 assert all(v==before['materials'][k] for k,v in after['materials'].items() if k not in allowed_materials)
 assert before['camera']==after['camera'] and before['settings']==after['settings']
 assert not bpy.data.libraries
 assert all(im.packed_file for im in bpy.data.images if im.users and im.source=='FILE')
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'initial.blend'));s.render.filepath=str(out/'initial.png');bpy.ops.render.render(write_still=True)
 report={'key':key,'scope':'Native pair integrity, not model evaluation','source':src.relative_to(ROOT).as_posix(),'target_objects_removed':removed,'target_materials':allowed_materials,'private_original_values':changes,'preserved_mesh_count':len(after['objects']),'preserved_meshes_equal':True,'preserved_materials_equal':True,'camera_and_render_settings_equal':True,'settings':after['settings'],'missing_active_images':0,'external_libraries':0,'input_embedded_texts':len(bpy.data.texts)}
 (out/'pair-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');(out/'preserved-baseline.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
 print('EDIT_PAIR_VALIDATED',key,len(removed),len(changes),flush=True)
