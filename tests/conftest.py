"""Explicit doubles for L1 orchestration tests; never applied automatically."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from harness.L1.common import resources
from harness.L1.common.attempt_log import sha256


@pytest.fixture
def no_blender_sandbox(monkeypatch):
    """Tests of non-sandbox behavior opt in; never claim actual discovery."""
    from harness.L1.common import blender_executor

    monkeypatch.setattr(blender_executor, "prepare_blender_sandbox", lambda *a, **k: {
        "result": {"prefix": [], "status": "test_double"},
        "execution": {"status": "test_double", "pid": None},
    })


@pytest.fixture
def fake_rerun_launcher(monkeypatch):
    """Explicit state-machine seam, never evidence of actual launcher discovery."""
    from harness.L1.common import rerun

    def resolve(requested, *, deadline):
        return {"result": {"requested": requested, "path": "/fixture/blender"},
                "execution": {"status": "test_double", "pid": None,
                              "deadline_monotonic": deadline},
                "test_only": "No executable discovered or launched"}

    monkeypatch.setattr(rerun, "resolve_executable", resolve)


@pytest.fixture
def fake_json_persistence(monkeypatch):
    """Synthetic-clock state-machine tests only; never claim real writer PIDs."""
    from src.evaluator.l1_persistence import JsonPersistence

    def write(self, path, value, *, cleanup=False, replace=True):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        if not replace and (path.exists() or path.is_symlink()):
            raise FileExistsError(path)
        path.write_bytes(data)
        row = {
            "protocol": "l1-json-persistence-v1", "status": "completed",
            "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "scope": "failure_cleanup" if cleanup else "evaluation",
            "deadline_monotonic": self.deadline,
            "execution": {"status": "test_double", "pid": None},
            "test_only": "Synchronous write under a synthetic clock; not subprocess evidence",
        }
        if cleanup:
            self.begin_cleanup()
        self.records.append(row)
        return row

    monkeypatch.setattr(JsonPersistence, "write", write)


@pytest.fixture
def fake_image_snapshot(monkeypatch):
    """Pair dummy scene bytes with a dummy worker, retaining real bridge/audits.

    Only tests that already replace the candidate executor opt in. Real Blender
    integration tests do not request this fixture. No fake PID/cost is recorded.
    """
    calls = []

    def snapshot(blender, source, output, *, authority, frames, timeout, deadline, glb_source):
        source, output, glb_source = Path(source), Path(output), Path(glb_source)
        calls.append({'source': source, 'output': output, 'authority': authority,
                      'frames': frames, 'deadline': deadline})
        frozen = output / 'snapshot'
        frozen.mkdir(parents=True)
        for name, path in [('scene.blend', source), ('scene.glb', glb_source)]:
            shutil.copy2(path, frozen / name)
        result = {'protocol': 'l1-image-dependency-snapshot-v1', 'status': 'ready', 'images': [],
                  'output_scene': str(frozen / 'scene.blend'), 'output_sha256': sha256(frozen / 'scene.blend'),
                  'glb': {'output': str(frozen / 'scene.glb'), 'output_sha256': sha256(frozen / 'scene.glb')},
                  'source_sha256': sha256(source), 'authority': authority, 'frames': list(frames),
                  'test_only': 'No Blender or image parsing performed'}
        (output / 'request.json').write_text(json.dumps({'authority': authority, 'frames': frames}))
        (output / 'result.json').write_text(json.dumps(result))
        worker = {'status': 'test_double', 'request_sha256': sha256(output / 'request.json'),
                  'result_sha256': sha256(output / 'result.json')}
        (output / 'worker_record.json').write_text(json.dumps(worker))
        return {**result, 'resource_execution': worker}

    monkeypatch.setattr(resources, 'snapshot_images', snapshot)
    return calls
