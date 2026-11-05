"""Runs inside Blender's isolated candidate process; never produces trusted facts."""
import os
import random
import runpy

import bpy


def main():
    seed = int(os.environ["THREEDBENCH_SEED"])
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.cycles.seed = seed
    runpy.run_path("/work/solution.py", run_name="__main__")
    # A script may already have saved scene.blend; save its final in-memory scene.
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath="/work/scene.blend", check_existing=False)


if __name__ == "__main__":
    import sys
    import traceback
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)
