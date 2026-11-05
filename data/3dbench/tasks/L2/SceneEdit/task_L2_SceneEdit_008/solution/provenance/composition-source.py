import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'assets/expansion/kenney';OUT=ROOT/'assets/expansion/artist_edits';bpy.context.preferences.filepaths.save_version=0
def mat(name,c):
 m=bpy.data.materials.new(name);m.diffuse_color=(*c,1);m.use_nodes=True;m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*c,1);m.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=.75;return m
def cube(name,pos,size,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=pos);o=bpy.context.object;o.name=name;o.scale=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m);return o
import sys
for pack in (sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else ['furniture-kit','racing-kit','train-kit']):
 bpy.ops.wm.read_factory_settings(use_empty=True);s=bpy.context.scene;s.unit_settings.system='METRIC';used={};targets=[];placements=[]
 def asset(name,pos,scale=1,angle=0,target=False):
  path=next((BASE/pack/'original').rglob(name+'.glb'));before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(path));objects=set(bpy.data.objects)-before;bpy.context.view_layer.update();points=[o.matrix_world@Vector(v) for o in objects if o.type=='MESH' for v in o.bound_box];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);pivot=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));root=bpy.data.objects.new(name+' placement',None);s.collection.objects.link(root)
  for o in objects:
   if o.parent not in objects:world=o.matrix_world.copy();o.parent=root;o.matrix_world=world
  root.matrix_world=Matrix.Translation(Vector(pos))@Matrix.Rotation(math.radians(angle),4,'Z')@Matrix.Scale(scale,4)@Matrix.Translation(-pivot)
  if target:targets.extend(o.name for o in objects);targets.append(root.name)
  used[name]={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};placements.append({'name':name,'position':pos,'scale':scale,'yaw':angle,'target':target})
 stone=mat('Original paving',(.49,.48,.43));sand=mat('Original ground',(.38,.42,.29));white=mat('Original walls',(.76,.73,.63));dark=mat('Original dark metal',(.09,.12,.14));wood=mat('Original wood',(.32,.16,.08));red=mat('Original shelter roof',(.42,.12,.07))
 if pack=='furniture-kit':
  cube('Cafe floor',(0,0,-.1),(8,7,.2),stone);cube('Rear wall',(0,3.6,1.5),(8,.2,3),white);cube('Left wall',(-4.1,0,1.5),(.2,7.4,3),white)
  for x,y in [(-2,1),(-2,-1.5),(1,-1.5)]:
   asset('tableRound',(x,y,0),2)
   for dx,dy,a in [(-1,0,90),(1,0,-90),(0,-1,0),(0,1,180)]:asset('chairRounded',(x+dx,y+dy,0),2,a)
  for x in [.75,1.61,2.47]:asset('kitchenCabinet',(x,2.9,0),2);asset('kitchenBar',(x,1.55,0),2,target=True)
  asset('kitchenBarEnd',(.22,1.55,0),2,target=True);asset('kitchenBarEnd',(3,1.55,0),2,180,True)
  asset('kitchenCoffeeMachine',(2.1,1.55,.84),2,target=True);asset('kitchenFridgeSmall',(3.4,2.8,0),2);asset('bookcaseOpen',(-2,3.12,0),2)
  for p in [(-3.4,2.8,0),(3.4,-2.9,0)]:asset('pottedPlant',p,2)
  camera=(10,-12,10);look=(0,0,1);ortho=13
 elif pack=='racing-kit':
  cube('Raceway site',(0,0,-.2),(27,38,.4),sand)
  for y in range(-15,16,6):asset('roadStraight',(0,y,0),6)
  for y in [-9,-3,3]:asset('pitsGarage',(8,y,0),5.5,-90,True)
  asset('pitsOffice',(8,9,0),5.5,-90,True);asset('grandStandCovered',(-7,1,0),6,90,True)
  asset('overhead',(0,-12,.1),5);asset('raceCarRed',(0,-5,.12),2.2);asset('raceCarOrange',(1,4,.12),2.2)
  for y in [-15,-12,-9,-6,6,9,12,15]:asset('barrierWhite',(-3.5,y,.02),3,90)
  camera=(33,-42,31);look=(0,0,2);ortho=46
 else:
  cube('Rail yard',(0,0,-.25),(24,44,.5),sand)
  for x in [0,5]:
   for y in [-16,-8,0,8,16]:asset('railroad-straight',(x,y,0),2)
  asset('train-locomotive-a',(0,10,.18),2);asset('train-carriage-box',(0,4,.18),2,target=True);asset('train-carriage-flatbed',(0,-2,.18),2)
  asset('train-carriage-tank',(5,-7,.18),2);cube('Raised platform',(-3.5,0,.45),(3,28,.9),stone)
  for y in [-8,-4,0,4,8]:cube('Shelter post',(-4.3,y,2.3),(.18,.18,2.8),dark)
  cube('Platform canopy',(-3.8,0,3.8),(3.5,20,.2),red)
  cube('Warehouse',(-8,9,2.6),(5,10,5.2),white);cube('Warehouse roof',(-8,9,5.3),(5.6,10.6,.3),red)
  for y in [6.5,10.5]:cube('Warehouse loading door',(-5.48,y,1.5),(.05,2.8,3),dark)
  for x,y in [(-8,-9),(-8,-6),(-6,-10)]:cube('Original cargo crate',(x,y,.65),(1.2,1.2,1.3),wood)
  camera=(33,-43,32);look=(0,0,1);ortho=48
 world=bpy.data.worlds.new('Original scene daylight');s.world=world;world.use_nodes=True;world.node_tree.nodes.get('Background').inputs[0].default_value=(.64,.75,.9,1);world.node_tree.nodes.get('Background').inputs[1].default_value=.35
 bpy.ops.object.light_add(type='AREA',location=(-12,-16,30));o=bpy.context.object;o.data.energy=11000;o.data.shape='DISK';o.data.size=20;o.rotation_euler=(Vector(look)-o.location).to_track_quat('-Z','Y').to_euler()
 bpy.ops.object.camera_add(location=camera);cam=bpy.context.object;cam.rotation_euler=(Vector(look)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=ortho;cam.data.clip_end=1000;s.camera=cam
 s.render.engine='CYCLES';s.cycles.samples=24;s.cycles.use_denoising=True;s.view_settings.view_transform='AgX';s.render.resolution_x=1200;s.render.resolution_y=1000;s.render.resolution_percentage=100
 out=OUT/pack;out.mkdir(parents=True,exist_ok=True);bpy.context.view_layer.update();bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(out/'reference.blend'));s.render.filepath=str(out/'reference.png');bpy.ops.render.render(write_still=True)
 before={o.name:hashlib.sha256(str(([list(v.co) for v in o.data.vertices],[list(v) for v in o.matrix_world])).encode()).hexdigest() for o in s.objects if o.type=='MESH'}
 for name in targets:
  if name in bpy.data.objects:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
 bpy.data.orphans_purge(do_local_ids=True,do_linked_ids=True,do_recursive=True);bpy.context.view_layer.update();after={o.name:hashlib.sha256(str(([list(v.co) for v in o.data.vertices],[list(v) for v in o.matrix_world])).encode()).hexdigest() for o in s.objects if o.type=='MESH'}
 assert all(before[k]==v for k,v in after.items());assert set(before)-set(after)==set(targets).intersection(before)
 bpy.ops.wm.save_as_mainfile(filepath=str(out/'initial.blend'));s.render.filepath=str(out/'initial.png');bpy.ops.render.render(write_still=True)
 (out/'pair-audit.json').write_text(json.dumps({'key':pack,'target_objects_removed':targets,'preserved_mesh_count':len(after),'preserved_meshes_equal':True,'preserved_materials_equal':True,'camera_and_render_settings_equal':True,'missing_active_images':0,'external_libraries':0,'scope':'Pair construction: only named target objects deleted; actual full and input renders.'},indent=2),encoding='utf-8');(out/'preserved-baseline.json').write_text(json.dumps(after,indent=2),encoding='utf-8');(out/'composition.json').write_text(json.dumps({'used_assets':used,'placements':placements,'source':'https://kenney.nl/assets/'+pack,'license':'CC0-1.0','changes':'Original full scene layout and procedural site context; selected licensed asset assembly deleted from model input.'},indent=2),encoding='utf-8');print('KENNEY_EDIT_VALIDATED',pack,flush=True)
