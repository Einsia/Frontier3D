"""Public-instruction lathed sleeve; static part, no private geometry."""
import argparse
import math
import sys
from pathlib import Path

import bpy

p=argparse.ArgumentParser()
p.add_argument('--input-dir',type=Path,required=True)
p.add_argument('--output-dir',type=Path,required=True)
args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
profile=[(17.205,0),(18.105,.9),(18.105,47.77),(15.895,47.77),
         (15.895,53.83),(18.105,53.83),(18.105,79.7),(17.205,80.6),
         (8.85,80.6),(7.95,79.7),(7.95,.9),(8.85,0)]
segments=128
vertices=[(r/1000*math.cos(i*2*math.pi/segments),
           r/1000*math.sin(i*2*math.pi/segments),z/1000)
          for r,z in profile for i in range(segments)]
faces=[]
for j in range(len(profile)):
    k=(j+1)%len(profile)
    for i in range(segments):
        nxt=(i+1)%segments
        faces.append((j*segments+i,j*segments+nxt,k*segments+nxt,k*segments+i))
mesh=bpy.data.meshes.new('Machined profile')
mesh.from_pydata(vertices,[],faces)
mesh.update()
obj=bpy.data.objects.new('Grooved sleeve',mesh)
bpy.context.scene.collection.objects.link(obj)
mat=bpy.data.materials.new('Blue-gray metal')
mat.diffuse_color=(.16,.26,.36,1)
mat.use_nodes=True
node=mat.node_tree.nodes.get('Principled BSDF')
node.inputs['Base Color'].default_value=(.16,.26,.36,1)
node.inputs['Metallic'].default_value=.7
node.inputs['Roughness'].default_value=.35
mesh.materials.append(mat)
scene=bpy.context.scene
scene.unit_settings.system='METRIC'
scene.unit_settings.scale_length=1
scene.frame_set(1)
args.output_dir.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'),export_format='GLB',export_animations=False)
