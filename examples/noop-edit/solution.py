"""Diagnostic no-op edit: preserves input geometry and should lose target credit."""
import argparse
from pathlib import Path
import sys
import bpy

parser=argparse.ArgumentParser()
parser.add_argument("--input-dir",type=Path,required=True)
parser.add_argument("--output-dir",type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index("--")+1:])
bpy.ops.wm.open_mainfile(filepath=str(args.input_dir/"initial.blend"))
args.output_dir.mkdir(parents=True,exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(args.output_dir/"scene.blend"))
bpy.ops.export_scene.gltf(filepath=str(args.output_dir/"scene.glb"),export_format="GLB")
