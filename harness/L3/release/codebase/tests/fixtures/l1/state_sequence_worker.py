"""Trusted test-only fault injection; never loaded from a candidate submission."""

import importlib.util
import os
from pathlib import Path

import bpy

worker_path = Path(__file__).resolve().parents[3] / "src/evaluator/l1_blender.py"
spec = importlib.util.spec_from_file_location("sequence_test_worker", worker_path)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
collect = worker._collect_state
calls = 0


def injected_collect(*args, **kwargs):
    global calls
    calls += 1
    if calls == 2:
        variant = os.environ["L1_TEST_SEQUENCE_FAULT"]
        if variant == "deform":
            obj = bpy.data.objects["moving"]
            # Keep the object's matrix and bounding dimensions unchanged, but
            # alter the real surface. A reload at frame 1 would conceal this.
            obj.data.vertices[0].co.x += .001
            obj.data.update()
        elif variant == "timeout":
            # The parent must kill the real inspector, retaining one snapshot.
            while True:
                pass
        elif variant == "error":
            raise RuntimeError("Intentional second-frame collection failure")
    return collect(*args, **kwargs)


worker._collect_state = injected_collect
try:
    worker.main()
except BaseException:  # noqa: BLE001 - real worker exit boundary under fault injection
    os._exit(1)
os._exit(0)
