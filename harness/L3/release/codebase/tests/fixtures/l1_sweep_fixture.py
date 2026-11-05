"""Controlled mutations of the public Text014 construction, never private GT."""
import json
import os
import runpy
from pathlib import Path

import bpy

root=Path(__file__).resolve().parent
result=runpy.run_path(str(root/'base_solution.py'),run_name='__main__')
args=result['args']
control=json.loads((root/'control.json').read_text())
variant=control.get('seed_variants',{}).get(os.environ.get('THREEDBENCH_SEED'),control['variant'])
obj,=[o for o in bpy.context.scene.objects if o.type=='MESH']
if variant=='permuted':
    vertices=[tuple(v.co) for v in obj.data.vertices]
    faces=[list(p.vertices) for p in reversed(obj.data.polygons)]
    material=obj.data.materials[0]
    mesh=bpy.data.meshes.new('Equivalent reordered surface')
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    mesh.materials.append(material)
    obj.data=mesh
elif variant=='wrong_depth':
    for vertex in obj.data.vertices:
        vertex.co.y*=1+.001/.0069
elif variant=='wrong_bend':
    import math
    for vertex in obj.data.vertices:
        vertex.co.x+=.001*math.exp(-((vertex.co.z-.0212)/.003)**2)
elif variant!='nominal':
    raise ValueError('Unknown swept-bar control')
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/'scene.blend'))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/'scene.glb'),export_format='GLB',export_animations=False)
