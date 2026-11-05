"""Three-round workflow fixture: real RNG draws and an intentional timeout."""

import json
import os
import random
import time
from pathlib import Path

import bpy
import numpy as np

config = json.loads(Path('round.json').read_text())
round_index = int(os.environ['THREEDBENCH_REPAIR_ROUND'])
seed = int(os.environ['THREEDBENCH_SEED'])
assert round_index == config['repair_round']
random.seed(seed)
np.random.seed(seed)
local_random = random.Random(seed)
local_numpy = np.random.default_rng(seed)
draws = {
    'python_module': [random.random() for _ in range(round_index + 1)],
    'numpy_module': np.random.random(round_index + 1).tolist(),
    'python_instance': [local_random.random() for _ in range(round_index + 1)],
    'numpy_instance': local_numpy.random(round_index + 1).tolist(),
}
Path('observed.json').write_text(json.dumps({'repair_round': round_index, 'program_seed': seed, 'draws': draws}))
if config.get('hang_seed') == seed:
    Path('intentional-timeout.json').write_text(json.dumps({'pid': os.getpid(), 'repair_round': round_index, 'program_seed': seed}))
    time.sleep(120)
bpy.ops.mesh.primitive_cube_add(size=.01)
bpy.context.object['round_draws'] = json.dumps(draws)
bpy.ops.export_scene.gltf(filepath='scene.glb', export_format='GLB', export_animations=False)
