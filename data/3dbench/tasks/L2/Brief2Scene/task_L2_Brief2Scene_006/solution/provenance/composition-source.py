"""Assemble six distinct licensed asset packs into full review-only scene examples."""
import bpy,math,json,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'assets/expansion/kenney';bpy.context.preferences.filepaths.save_version=0
PACKS=['pirate-kit','space-kit','city-kit-suburban','castle-kit','graveyard-kit','minigolf-kit']
if '--' in sys.argv:PACKS=sys.argv[sys.argv.index('--')+1:]
def material(name,color,rough=.8):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True;m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*color,1);m.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value=rough;return m
def cube(name,pos,size,mat):
 bpy.ops.mesh.primitive_cube_add(size=1,location=pos);o=bpy.context.object;o.name=name;o.scale=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);return o
for pack in PACKS:
 bpy.ops.wm.read_factory_settings(use_empty=True);scene=bpy.context.scene;scene.unit_settings.system='METRIC';folder=BASE/pack;dest=folder/'review';dest.mkdir(exist_ok=True);used={};placements=[]
 def asset(name,pos,scale=1,angle=0):
  path=next((folder/'original').rglob(name+'.glb'));before=set(bpy.data.objects);bpy.ops.import_scene.gltf(filepath=str(path));objects=set(bpy.data.objects)-before;bpy.context.view_layer.update();points=[o.matrix_world@Vector(v) for o in objects if o.type=='MESH' for v in o.bound_box];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);pivot=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));root=bpy.data.objects.new(name+' placement',None);scene.collection.objects.link(root)
  for o in objects:
   if o.parent not in objects:world=o.matrix_world.copy();o.parent=root;o.matrix_world=world
  rotation=Matrix.Rotation(math.radians(angle),4,'Z');root.matrix_world=Matrix.Translation(Vector(pos))@rotation@Matrix.Scale(scale,4)@Matrix.Translation(-pivot)
  used[name]={'path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()};placements.append({'asset':name,'ground_position':pos,'uniform_scale':scale,'yaw_degrees':angle});return (hi-lo)*scale
 grass=material('Original site grass',(.28,.43,.21));sand=material('Original site sand',(.69,.53,.32));road=material('Original road surface',(.12,.15,.17));stone=material('Original paved surface',(.53,.55,.5));water=material('Original water',(.015,.26,.4),.22);wood=material('Original pier walkway',(.32,.17,.085));white=material('Original paint',(.85,.85,.75));dirt=material('Original ground',(.13,.2,.18))
 if pack=='city-kit-suburban':
  cube('Neighbourhood site',(0,0,-.25),(32,34,.5),grass);cube('Two way street',(0,0,.01),(6,34,.08),road)
  for x in [-3.65,3.65]:cube('Continuous sidewalk',(x,0,.12),(1.3,34,.18),stone)
  for y in range(-15,16,4):cube('Lane dash',(0,y,.06),(.13,2,.02),white)
  houses=['building-type-a','building-type-b','building-type-g','building-type-j','building-type-o','building-type-u']
  for i,name in enumerate(houses):
   side=-1 if i<3 else 1;y=[-10,0,10][i%3];asset(name,(side*9,y,0),4.5,90 if side<0 else -90);cube('Driveway',(side*5.8,y-2,.07),(3.3,2.4,.08),stone);asset('planter',(side*5,y+2,.12),3,90)
   for yy in [-3.5,3.5]:asset('tree-small',(side*13.6,y+yy,0),5)
  camera=(40,-45,37);look=(0,0,1);ortho=47
 elif pack=='pirate-kit':
  cube('Sea',(0,0,-.35),(34,32,.6),water);cube('Quay island',(9,2,-.1),(13,27,1.2),sand);cube('Dock trunk',(1,-3,.8),(4,19,.5),wood);cube('Dock finger',(-3,-8,.84),(9,3,.5),wood)
  for y in [-10,-5,0,5]:asset('structure-platform-dock',(1,y,-.5),1.5)
  asset('ship-large',(-7,4,-.7),1,0);asset('boat-row-large',(-7,-10,-.3),1.1,90)
  asset('structure',(9,5,.5),2);asset('structure-roof',(9,5,4.9),2)
  asset('tower-complete-small',(11,-7,.5),1)
  for x,y in [(13,10),(12,-11),(6,11),(5,-9)]:asset('palm-detailed-bend',(x,y,.5),1.1,20*x)
  for i in range(5):asset('barrel',(4+i*1.1,0,.5),.7,0);asset('crate',(4+i*1.1,-1.6,.5),.8,0)
  for x,y in [(-1,11),(5,-12),(14,-3)]:asset('rocks-sand-a',(x,y,-.1),.7)
  camera=(37,-45,32);look=(0,0,2);ortho=44
 elif pack=='space-kit':
  cube('Outpost terrain',(0,0,-.3),(36,32,.6),sand);cube('Work apron',(4,0,.02),(16,18,.1),stone)
  asset('hangar_largeA',(6,5,.08),3);asset('hangar_roundGlass',(6,-6,.08),2.3)
  asset('satelliteDish_large',(13,10,.08),4,35);asset('machine_generatorLarge',(-.5,8,.08),3)
  for y in [-6,-3,0]:asset('rover',(2,y,.08),3,40)
  for y in [-10,-7,-4,-1,2,5,8]:
   asset('monorail_trackStraight',(-9,y,2.7),3);cube('Rail support',(-9,y,1.35),(.55,.55,2.7),stone)
  asset('monorail_trainFront',(-9,-4,3.0),2.2)
  asset('rocket_baseA',(-2,-10,.08),1.7);asset('rocket_fuelA',(-2,-10,2.8),1.7);asset('rocket_fuelA',(-2,-10,3.65),1.7);asset('rocket_topA',(-2,-10,4.5),1.7)
  for x,y in [(-13,9),(12,-12),(-12,-12),(0,13)]:asset('crater',(x,y,-.02),4)
  for y in [2,5]:asset('pipe_straight',(-2,y,.08),2)
  camera=(40,-45,40);look=(0,0,1);ortho=46
 elif pack=='castle-kit':
  cube('Castle island',(0,0,-.35),(29,28,.7),grass);cube('Courtyard',(0,0,.02),(17,17,.1),stone)
  for y in [-6,-3,0,3,6]:asset('wall',(-9,y,0),3);asset('wall',(9,y,0),3)
  for x in [-6,-3,0,3,6]:asset('wall',(x,9,0),3,90)
  for x in [-6,-3,3,6]:asset('wall',(x,-9,0),3,90)
  asset('wall-doorway',(0,-9,0),3,90);asset('gate',(0,-9,.05),3,90);asset('bridge-draw',(0,-11.8,.05),3,90)
  for x in [-9,9]:
   for y in [-9,9]:asset('tower-square-base',(x,y,0),3);asset('tower-square-mid',(x,y,3.0),3);asset('tower-square-top',(x,y,6.0),3)
  asset('tower-square-base',(0,4,0),4);asset('tower-square-mid',(0,4,4),4);asset('tower-square-roof',(0,4,8),4)
  asset('stairs-stone',(-6,4,0),4,180);asset('siege-catapult',(3,-3,.08),2,15);asset('tree-large',(-5,-2,.08),2)
  camera=(35,-44,37);look=(0,0,4);ortho=42
 elif pack=='graveyard-kit':
  cube('Graveyard site',(0,0,-.2),(24,24,.4),dirt);cube('Central path',(0,-1,.01),(2.8,22,.08),stone)
  for x in [-7,-4,4,7]:
   for y in [-7,-3,1]:asset('grave',(x,y,.02),1.4);asset('gravestone-round' if x<0 else 'gravestone-cross',(x,y+.7,.08),1.7,180)
  asset('crypt-large',(0,7,0),2.2);asset('crypt-large-roof',(0,7,2.2),2.2);asset('crypt-large-door',(0,4.32,.02),2.2)
  for t in range(-9,10,2):
   asset('iron-fence',(t,11,0),2);asset('iron-fence',(-11,t,0),2,90);asset('iron-fence',(11,t,0),2,90)
   if abs(t)>1:asset('iron-fence',(t,-11,0),2)
  asset('iron-fence-border-gate',(0,-11,0),2)
  for x,y in [(-8,7),(8,7),(-9,-9),(9,-9)]:asset('pine-crooked',(x,y,0),2.2)
  for y in [-8,-2,4]:asset('lightpost-single',(-1.9,y,0),2)
  camera=(31,-37,29);look=(0,0,1);ortho=36
 else:
  cube('Minigolf park',(0,0,-.25),(25,26,.5),grass)
  for lane,x in enumerate([-7,0,7]):
   for i,name in enumerate(['start','straight','straight','obstacle-diamond','hole-round']):asset(name,(x,-8+i*4,0),4,180 if name=='hole-round' else 0)
   if lane==0:asset('windmill',(x,0,.02),2.4)
   if lane==1:asset('castle',(x,-3,.02),2.8)
   asset('flag-red',(x,8,.35),1.6);asset('ball-red',(x,-8,.36),1.5)
   cube('Entry paving',(x,-10.8,.02),(4,1.6,.08),stone)
  cube('Visitor path',(0,-12.2,.02),(24,1.2,.08),stone);camera=(32,-39,33);look=(0,0,.5);ortho=38
 world=bpy.data.worlds.new('Original daylight');scene.world=world;world.use_nodes=True;world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.64,.75,.9,1);world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.35
 bpy.ops.object.light_add(type='AREA',location=(-12,-16,30));light=bpy.context.object;light.data.energy=11000;light.data.shape='DISK';light.data.size=20;light.rotation_euler=(Vector(look)-light.location).to_track_quat('-Z','Y').to_euler()
 bpy.ops.object.camera_add(location=camera);cam=bpy.context.object;cam.rotation_euler=(Vector(look)-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.type='ORTHO';cam.data.ortho_scale=ortho;cam.data.clip_end=1000;scene.camera=cam
 alt=cam.copy();alt.data=cam.data.copy();scene.collection.objects.link(alt);alt.name='Review alternate';alt.location+=cam.rotation_euler.to_quaternion()@Vector((.3,0,0))
 scene.render.engine='CYCLES';scene.cycles.samples=24;scene.cycles.use_denoising=True;scene.render.resolution_x=1200;scene.render.resolution_y=1000;scene.render.resolution_percentage=100;scene.view_settings.view_transform='AgX';scene.render.filepath=str(dest/'main.png');bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(dest/'scene.blend'));bpy.ops.render.render(write_still=True)
 (dest/'provenance.json').write_text(json.dumps({'pack':pack,'license':'CC0-1.0','source':'https://kenney.nl/assets/'+pack,'used_assets':used,'placements':placements,'modifications':'Original scene composition, procedural ground/roads/piers, imported licensed asset geometry. Example for text brief review only; not a pixel-exact ground truth.'},indent=2),encoding='utf-8');print('SCENE_COMPLETE',pack,flush=True)
