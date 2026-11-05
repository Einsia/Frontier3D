"""Native-engine controls derived only from the synthetic saved-camera fixture."""
import sys
from pathlib import Path

import bpy

source, root = (Path(p) for p in sys.argv[sys.argv.index('--')+1:])
root.mkdir(parents=True, exist_ok=False)
for engine in ('BLENDER_EEVEE', 'BLENDER_WORKBENCH'):
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    scene.render.engine = engine
    scene.render.filepath = str(root/(engine+'.png'))
    if engine == 'BLENDER_WORKBENCH':
        scene.display.shading.color_type = 'MATERIAL'
        scene.display.shading.light = 'STUDIO'
    bpy.ops.wm.save_as_mainfile(filepath=str(root/(engine+'.blend')))
    bpy.ops.render.render(write_still=True)
