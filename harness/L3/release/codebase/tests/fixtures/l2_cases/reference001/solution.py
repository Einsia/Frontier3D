"""Public contract fixture: a desk-shaped proxy, deliberately not a classroom answer."""
import argparse
from pathlib import Path
import sys
import bpy
from mathutils import Vector

parser=argparse.ArgumentParser()
parser.add_argument('--input-dir',type=Path,required=True)
parser.add_argument('--output-dir',type=Path,required=True)
a=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
out=a.output_dir
scene=bpy.context.scene
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
scene.unit_settings.system='METRIC';scene.unit_settings.scale_length=1
scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=4
scene.cycles.use_denoising=False
scene.render.resolution_x=800;scene.render.resolution_y=450;scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.view_settings.view_transform='Standard';scene.view_settings.look='None'
scene.view_settings.exposure=0;scene.view_settings.gamma=1
scene.world=bpy.data.worlds.new('World');scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.5,.5,.5,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.7
for location,dimensions in [((0,0,.725),(1.2,.7,.05)), *(( (x,y,.35),(.06,.06,.70)) for x in (-.53,.53) for y in (-.28,.28))]:
 bpy.ops.mesh.primitive_cube_add(size=1,location=location)
 obj=bpy.context.object;obj.dimensions=dimensions;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
mat=bpy.data.materials.new('Wood');mat.diffuse_color=(.35,.15,.05,1)
for obj in scene.objects:
 if obj.type=='MESH':obj.data.materials.append(mat)
for name,location in [('arbitrary primary name',(3,-4,2.4)),('unrelated secondary name',(3,-4,2.4))]:
 data=bpy.data.cameras.new(name);cam=bpy.data.objects.new(name,data);scene.collection.objects.link(cam)
 cam.location=location;cam.rotation_euler=(Vector((0,0,.5))-cam.location).to_track_quat('-Z','Y').to_euler();data.lens=42
primary=scene.objects['arbitrary primary name'];secondary=scene.objects['unrelated secondary name']
bpy.context.view_layer.update()
secondary.location=primary.location+(primary.rotation_euler.to_matrix()@Vector((.30,0,0)))
for camera,name in ((primary,'main.png'),(secondary,'alternate.png')):
 scene.camera=camera;scene.render.filepath=str(out/name);bpy.ops.render.render(write_still=True)
scene.camera=primary
bpy.ops.wm.save_as_mainfile(filepath=str(out/'scene.blend'))
