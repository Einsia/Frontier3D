"""Exercise shared scene helpers after removal of unused evaluation workflows."""
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent_judge.protocol import digest, write_json
from tools import native_scene, saved_scene_render, scene_render


def pointer(path):
    return {'path': str(path), 'sha256': digest(path)}


def test_current_evaluation_imports_do_not_load_retired_workflows():
    from tools import evaluate_linear_candidate, measure_effort_legacy_detail
    from tools import measure_interactive_detail, measure_effort_addition_integrity

    assert evaluate_linear_candidate.render is scene_render.render
    assert measure_effort_legacy_detail.render is scene_render.render
    assert measure_interactive_detail.inspect is native_scene.inspect
    assert measure_effort_addition_integrity.saved_render is saved_scene_render.saved_render


def test_fixed_view_render_cache_rechecks_scene_and_images(tmp_path, monkeypatch):
    monkeypatch.setenv('THREEDBENCH_RUN_ROOT', str(tmp_path))
    scene = tmp_path / 'scene.blend'
    scene.write_bytes(b'candidate scene')
    image = tmp_path / 'view.png'
    image.write_bytes(b'cached image')
    output = tmp_path / 'render'
    output.mkdir()
    source = pointer(scene)
    views = [{'id': 'primary', 'frame': 1, 'resolution': [64, 64], 'image': str(image)}]
    write_json(output / 'request.json', {'scene': str(scene), 'scene_sha256': source['sha256'],
               'views': views, 'result': str(output / 'renders.json')})
    result = {'worker_sha256': digest(scene_render.ROOT / 'src/evaluator/continuous_render.py'),
              'scene_sha256': source['sha256'], 'source_unchanged': True,
              'views': {'primary': {'frame': 1, 'resolution': [64, 64], 'image': pointer(image)}}}
    write_json(output / 'renders.json', result)
    assert scene_render.render(source, views, output) == result
    image.write_bytes(b'tampered image')
    with pytest.raises(ValueError, match='Changed evidence'):
        scene_render.render(source, views, output)
    scene.write_bytes(b'tampered scene')
    with pytest.raises(ValueError, match='Changed evidence'):
        scene_render.render(source, views, output)


def test_native_inspection_checks_complete_scene_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv('THREEDBENCH_RUN_ROOT', str(tmp_path))
    scene = tmp_path / 'scene.blend'
    scene.write_bytes(b'candidate scene')
    source = pointer(scene)
    calls = []

    def worker(request, output):
        calls.append(request)
        return {'scene': source, 'source_unchanged': True, 'snapshots': []}

    monkeypatch.setattr(native_scene, 'worker', worker)
    assert native_scene.inspect(source, tmp_path / 'inspection', [1, 11])['source_unchanged']
    assert calls == [{'operation': 'inspect', 'scene': source, 'frames': [1, 11]}]
    monkeypatch.setattr(native_scene, 'worker', lambda *a: {'scene': source, 'source_unchanged': False})
    with pytest.raises(ValueError, match='Invalid scene extraction provenance'):
        native_scene.inspect(source, tmp_path / 'inspection')


@pytest.mark.parametrize('codes', [[0], [-signal.SIGSEGV, 0], [1]])
def test_saved_render_preserves_crash_retry_receipts(tmp_path, monkeypatch, codes):
    monkeypatch.setenv('THREEDBENCH_RUN_ROOT', str(tmp_path))
    scene = tmp_path / 'scene.blend'
    scene.write_bytes(b'candidate scene')
    source = pointer(scene)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        request_path = Path(command[-1])
        request = json.loads(request_path.read_text())
        output = request_path.parent
        code = codes[len(calls) - 1]
        if code == 0:
            image = output / 'primary_beauty.png'
            image.write_bytes(b'rendered image')
            write_json(output / 'result.json', {
                'request_sha256': digest(request_path),
                'worker_sha256': digest(saved_scene_render.WORKER),
                'renderer_sha256': digest(saved_scene_render.ROOT / 'src/evaluator/l1_image_blender.py'),
                'scene': source, 'source_unchanged': True, 'view': {'image': pointer(image)},
            })
        return SimpleNamespace(returncode=code)

    monkeypatch.setattr(saved_scene_render.subprocess, 'run', run)
    if codes == [1]:
        with pytest.raises(ValueError, match='Saved image render failed'):
            saved_scene_render.saved_render(source, tmp_path / 'renders', 1, [64, 64])
        assert len(calls) == 1
        return
    result, receipt = saved_scene_render.saved_render(source, tmp_path / 'renders', 1, [64, 64])
    assert result['scene'] == source
    execution = json.loads(Path(receipt['path']).with_name('execution.json').read_text())
    assert [a['returncode'] for a in execution['attempts']] == codes
    assert len(calls) == len(codes)
    saved_scene_render.saved_render(source, tmp_path / 'renders', 1, [64, 64])
    assert len(calls) == len(codes)  # Successful cache never launches another process.
    Path(result['view']['image']['path']).write_bytes(b'tampered image')
    with pytest.raises(ValueError, match='Native source changed'):
        saved_scene_render.saved_render(source, tmp_path / 'renders', 1, [64, 64])
