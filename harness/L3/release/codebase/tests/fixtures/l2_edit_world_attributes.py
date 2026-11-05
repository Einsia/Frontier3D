"""Blender save/reopen probe: world properties and metric cameras, no model submission."""
import argparse
import json
from pathlib import Path
import sys

import bpy

p=argparse.ArgumentParser();p.add_argument('--task',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
p.add_argument('--project',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(a.project/'src/evaluator'))
from l2_case_blender import properties,tree_signature


def facts():
    scene=bpy.context.scene;world=scene.world
    def cam(o):return {'location':list(o.matrix_world.translation),'basis_x':list(o.matrix_world.to_3x3().col[0])}
    return {'scene':{'objects':{},'light_data':{},'unit_scale':scene.unit_settings.scale_length,
        'world_data':{'properties':properties(world),'nodes':tree_signature(world.node_tree)},
        'cameras':{'__main':cam(scene.camera),**({'__alternate':cam(scene.objects['metric_alternate'])}
                   if 'metric_alternate' in scene.objects else {})}}}


bpy.ops.wm.open_mainfile(filepath=str(a.task/'solution/reference/scene.blend'),load_ui=False,use_scripts=False)
reference=facts()
goals={n.name:n.inputs['Strength'].default_value for n in bpy.context.scene.world.node_tree.nodes if n.type=='BACKGROUND'}
bpy.ops.wm.open_mainfile(filepath=str(a.task/'environment/input/initial.blend'),load_ui=False,use_scripts=False)
initial=facts();results={'reference':reference,'initial':initial}
for mode in ('correct','unchanged','wrong_strength','wrong_numeric'):
    bpy.ops.wm.open_mainfile(filepath=str(a.task/'environment/input/initial.blend'),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    if mode!='unchanged':
        for name,value in goals.items():scene.world.node_tree.nodes[name].inputs['Strength'].default_value=value*(.1 if mode=='wrong_strength' else 1.)
    main=scene.camera;alt=main.copy();alt.data=main.data.copy();alt.name='metric_alternate';scene.collection.objects.link(alt)
    alt.matrix_world=main.matrix_world.copy()
    alt.location=main.matrix_world.translation+main.matrix_world.to_3x3().col[0].normalized()*((.6 if mode=='wrong_numeric' else .3)/scene.unit_settings.scale_length)
    bpy.context.view_layer.update()
    filename=a.output/(mode+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(filename),compress=True)
    bpy.ops.wm.open_mainfile(filepath=str(filename),load_ui=False,use_scripts=False)
    results[mode]=facts()
(a.output/'facts.json').write_text(json.dumps(results,allow_nan=False,indent=2)+'\n')
