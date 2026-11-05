import bpy,sys,json,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[1];a=sys.argv[sys.argv.index('--')+1:];key=a[0];folder=R/'assets/cc0-replacements-20260921'/key;out=folder/'prepared';out.mkdir(exist_ok=True)
if key=='medieval-dungeon-interior':p=folder/'original/dungeon/blender/demo_scene.blend'
elif key=='attic-hideout':p=R/'assets/diverse/attic_hideout/source.blend'
elif key=='verdant-trail':p=R/'assets/diverse/verdant_trail/original/verdant_trail.blend'
else:
 src=json.loads((folder/'source.json').read_text());p=R/src['source_file'] if src.get('source_file','').endswith('.blend') else next(x for x in folder.rglob('*.blend') if 'prepared' not in str(x))
bpy.ops.wm.open_mainfile(filepath=str(p),load_ui=True,use_scripts=False);s=bpy.context.scene;bpy.context.preferences.filepaths.save_version=0;mods=[]
# Relink author dependencies before evaluation; nothing is synthesized.
lookup={}
for f in folder.rglob('*'):
 if f.is_file():lookup.setdefault(f.name.lower(),[]).append(f)
for lib in bpy.data.libraries:
 if not Path(bpy.path.abspath(lib.filepath)).is_file():
  cand=lookup.get(Path(lib.filepath.replace('\\','/')).name.lower(),[])
  if len(cand)==1:lib.filepath=str(cand[0]);lib.reload()
missing=[]
for im in list(bpy.data.images):
 if not im.users:continue
 if key=='3d-city' and im.name=='modern_buildings_2k.hdr':
  # source HDRI is absent; omit the source world and use neutral studio illumination.
  for n in s.world.node_tree.nodes if s.world and s.world.use_nodes else []:
   if n.type=='TEX_ENVIRONMENT' and n.image==im:n.image=None
  bpy.data.images.remove(im);mods.append('Missing source HDRI removed; author geometry and materials retained.');continue
 if key=='verdant-trail':
  f=R/'assets/diverse/verdant_trail/portable-textures'/Path(im.filepath.replace('\\','/')).name
  if f.exists():
   if im.packed_file:im.unpack(method='REMOVE')
   im.filepath=str(f)
 if key=='voxel-atolls' and im.filepath.lower().endswith('.psd'):
  im.filepath=str(folder/'textures/Atlas_WoodLand_EpicMobile.png')
 if im.source=='FILE' and not im.packed_file and not Path(bpy.path.abspath(im.filepath,library=im.library)).exists():
  match=lookup.get(Path(im.filepath.replace('\\','/')).name.lower(),[])
  if len(match)==1:im.filepath=str(match[0])
  else:missing.append(im.filepath)
if missing:raise RuntimeError('Unresolved source images '+repr(missing))
for screen in bpy.data.screens:
 for ar in screen.areas:
  if ar.type=='VIEW_3D':ar.spaces.active.shading.type='SOLID'
# linked geometry localized, retain authored positions
for block in list(bpy.data.user_map()):
 if block.library and block.bl_rna.identifier!='Library':
  try:block.make_local()
  except:pass
# make_local removes unused library datablocks automatically
s.render.engine='CYCLES';s.cycles.samples=12;s.cycles.use_denoising=True;s.cycles.device='CPU';s.render.threads_mode='FIXED';s.render.threads=8
s.render.use_simplify=True;s.render.simplify_subdivision_render=1;s.cycles.texture_limit_render='1024' if key!='verdant-trail' else '512'
s.render.resolution_percentage=100;s.render.resolution_x=960;s.render.resolution_y=640;s.render.use_compositing=False;s.render.use_sequencer=False;s.render.use_border=False;s.render.image_settings.media_type='IMAGE';s.render.image_settings.file_format='PNG';s.view_settings.view_transform='AgX';s.view_settings.exposure=0
if not s.camera:
 view=next((ar.spaces.active.region_3d for sc in bpy.data.screens for ar in sc.areas if ar.type=='VIEW_3D'),None)
 cam=bpy.data.objects.new('TaskCamera',bpy.data.cameras.new('TaskCamera'));s.collection.objects.link(cam);s.camera=cam
 if view:
  cam.matrix_world=view.view_matrix.inverted();cam.data.lens=40;mods.append('Camera from author saved viewport; no geometry added.')
 else:raise RuntimeError('No author camera or viewport')
# Add neutral daylight only where the source lacks light, without altering geometry/materials.
if key in ['home-bedroom','home-kitchen','3d-city','medieval-blacksmith','medieval-tavern','low-poly-terrain','voxel-atolls']:
 world=bpy.data.worlds.new('Preparation daylight');world.use_nodes=True;world.node_tree.nodes['Background'].inputs[0].default_value=(.65,.73,.85,1);world.node_tree.nodes['Background'].inputs[1].default_value=.45;s.world=world
 light=bpy.data.objects.new('Preparation sun',bpy.data.lights.new('Preparation sun','SUN'));s.collection.objects.link(light);light.data.energy=2.0;light.data.angle=.25;light.rotation_euler=(.5,-.45,-.8);mods.append('Neutral daylight to render author asset in current Blender; geometry and arrangement unchanged.')
if key=='3d-city':s.camera.data.type='ORTHO';s.camera.data.ortho_scale=22
if key in ['home-bedroom','home-kitchen']:
 # Open walls in authored cutaway scene; use the original viewport if available.
 s.camera.data.clip_end=1000
if key in ['home-bedroom','home-kitchen']:
 pos,look=((2.4,2.5,1.9),(-1.1,-1.0,1.0)) if key=='home-bedroom' else ((-2.35,-2.10,1.65),(.5,1.4,1.1))
 s.camera.location=pos;s.camera.rotation_euler=(Vector(look)-s.camera.location).to_track_quat('-Z','Y').to_euler();s.camera.data.type='PERSP';s.camera.data.lens=22
 light=bpy.data.objects.new('Preparation interior softbox',bpy.data.lights.new('Preparation interior softbox','AREA'));s.collection.objects.link(light);light.location=(0,0,2.3);light.data.energy=220;light.data.size=3
 mods.append('Placed camera inside room and added ceiling softbox; all source geometry retained.')
if key in ['voxel-atolls','space-hallways','medieval-dungeon-interior']:
 pos,look,lens={'voxel-atolls':((85,-105,95),(-5,-8,0),40),'space-hallways':((0,-9.2,1.4),(0,7,1.4),23),'medieval-dungeon-interior':((0,-5,1.6),(0,6,1.4),22)}[key]
 s.camera.location=pos;s.camera.rotation_euler=(Vector(look)-s.camera.location).to_track_quat('-Z','Y').to_euler();s.camera.data.type='PERSP';s.camera.data.lens=lens;s.camera.data.clip_end=2000
 mods.append('Camera framed inside the author demo layout; geometry not moved or added.')
 if key=='voxel-atolls':s.camera.data.type='ORTHO';s.camera.data.ortho_scale=135
 if key=='medieval-dungeon-interior':
  for i,pos in enumerate([(0,-4,2),(0,4,2),(0,10,3)]):
   light=bpy.data.objects.new('Preparation softbox '+str(i),bpy.data.lights.new('Preparation softbox '+str(i),'AREA'));s.collection.objects.link(light);light.location=pos;light.data.energy=300;light.data.size=4
  mods.append('Neutral ceiling illumination added to otherwise unlit source geometry.')

# Pack dependencies so tasks remain portable.
bpy.ops.file.pack_all();s.render.filepath=str(out/'main.png');bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'),compress=True)
report={'key':key,'source_file':str(p.relative_to(R)),'modifications':mods,'geometry_origin':'upstream author scene, no added modeled geometry','resolution':[960,640],'engine':'CYCLES','samples':12,'missing_dependencies':missing,'library_count':len(bpy.data.libraries),'camera_type':s.camera.data.type}
(out/'preparation.json').write_text(json.dumps(report,indent=2));bpy.ops.render.render(write_still=True);print('PREPARED_AUTHOR_SCENE',key,flush=True)
