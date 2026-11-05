"""Read-only native-surface supplement; never run candidate code or render."""
import argparse
import json
from pathlib import Path
import sys

import bpy
sys.path.insert(0,str(Path(__file__).resolve().parent))
import l2_case_dense
from l2_case_collector import _object_facts


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scene',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.open_mainfile(filepath=args.scene,load_ui=False,use_scripts=False)
    scene=bpy.context.scene;depsgraph=bpy.context.evaluated_depsgraph_get()
    output=Path(args.output)
    l2_case_dense.EVIDENCE_DIRECTORY=output.parent
    objects={}
    for obj in sorted(scene.objects,key=lambda o:o.name):
        if obj.type not in {'CURVE','SURFACE','FONT','META'}:continue
        fact=_object_facts(obj,depsgraph,scene.unit_settings.scale_length)
        if fact['visible_render']:objects[obj.name]=fact
    output.write_text(json.dumps({'unit_scale':scene.unit_settings.scale_length,'objects':objects}))


if __name__=='__main__':main()
