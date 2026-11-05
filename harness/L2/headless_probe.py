"""Small real renders; executed only by Blender inside the L2 sandbox."""
import json
import os
import sys
from pathlib import Path

import bpy
import gpu


def main():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    scene = bpy.context.scene
    scene.render.resolution_x = scene.render.resolution_y = 64
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.filepath = "/audit/eevee.png"
    bpy.ops.render.render(write_still=True)
    report = {"version": bpy.app.version_string, "gpu_vendor": gpu.platform.vendor_get(),
              "gpu_renderer": gpu.platform.renderer_get(), "gpu_version": gpu.platform.version_get()}
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.filepath = "/audit/cycles.png"
    bpy.ops.render.render(write_still=True)
    Path("/audit/probe.json").write_text(json.dumps(report, indent=2) + "\n")


try:
    main()
except Exception:
    import traceback
    traceback.print_exc()
    status = 1
else:
    status = 0
sys.stdout.flush()
sys.stderr.flush()
os._exit(status)
