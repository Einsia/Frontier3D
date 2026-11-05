"""Real native RNG paths intentionally outside the legacy wrapper counters."""

import json
import os
from pathlib import Path

import bpy
import numpy as np


def build(mode='extension_generator', stable_geometry=True, fixed_seed=None):
    seed = int(os.environ['THREEDBENCH_SEED']) if fixed_seed is None else fixed_seed
    if mode == 'extension_generator':
        from numpy.random._generator import Generator
        values = Generator(np.random.PCG64(seed)).random(4).tolist()
    elif mode == 'extension_randomstate':
        from numpy.random.mtrand import RandomState
        values = RandomState(seed).random(4).tolist()
    elif mode == 'raw_bitgenerator':
        values = np.random.PCG64(seed).random_raw(4).tolist()
    elif mode == 'c_api':
        generator = np.random.PCG64(seed)
        interface = generator.ctypes
        values = [interface.next_double(interface.state) for _ in range(4)]
    elif mode == 'blender_noise':
        from mathutils import noise
        noise.seed_set(seed + 1)  # Blender treats zero as a time-based seed.
        values = [noise.random() for _ in range(4)]
    elif mode == 'public':
        values = np.random.default_rng(seed).random(4).tolist()
    else:
        raise ValueError(mode)
    Path('rng-observed.json').write_text(json.dumps({'mode': mode, 'seed': seed, 'draws': values,
        'numpy_version': np.__version__, 'blender_version': list(bpy.app.version)}))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    size = .01 if stable_geometry else .01 + .02 * values[0]
    bpy.ops.mesh.primitive_cube_add(size=size)
    bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB', export_animations=False)
