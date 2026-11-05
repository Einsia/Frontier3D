"""Hash-bound scene rendering shared by the current scoring routes."""
import os
from pathlib import Path
import subprocess

from benchmark.resources import ROOT, blender_path
from src.agent_judge.protocol import digest, read_json, write_json

BLENDER = blender_path()
LEGACY_RENDER_WORKER_SHA256 = 'c079b57f8437f1ef4acfcb487f0f938b30f160126fac59b9fd02bee5d425f823'

def bound(path, expected=None):
    path = Path(path).resolve(strict=True)
    if not (path.is_relative_to(ROOT / 'data') or path.is_relative_to(Path(os.environ['THREEDBENCH_RUN_ROOT']))):
        raise ValueError('Evidence outside project data')
    sha = digest(path)
    if expected and sha != expected: raise ValueError('Changed evidence: ' + str(path))
    return {'path': str(path), 'sha256': sha}

def render(scene, views, output):
    # A matching request is insufficient if the referenced scene changed after
    # the successful render. Verify its actual bytes on both replay and fresh runs.
    bound(scene['path'], scene['sha256'])
    output.mkdir(parents=True, exist_ok=True)
    request = {'scene': scene['path'], 'scene_sha256': scene['sha256'], 'views': views,
               'result': str(output / 'renders.json')}
    if (output / 'renders.json').is_file():
        if read_json(output / 'request.json') != request: raise ValueError('Render cache request changed')
        result = read_json(output / 'renders.json')
        cached_worker = result['worker_sha256']
        legacy_cache = cached_worker != digest(ROOT / 'src/evaluator/continuous_render.py')
        if legacy_cache:
            legacy = ROOT / 'src/evaluator/continuous_render_legacy.py'
            if (cached_worker != LEGACY_RENDER_WORKER_SHA256 or not legacy.is_file()
                    or legacy.is_symlink() or digest(legacy) != LEGACY_RENDER_WORKER_SHA256):
                raise ValueError('Render worker changed; no matching trusted source archive')
        if result.get('scene_sha256') != scene['sha256'] or result.get('source_unchanged') is not True:
            raise ValueError('Render cache source binding changed')
        expected_views = {view['id']: view for view in views}
        if len(expected_views) != len(views) or set(result['views']) != set(expected_views):
            raise ValueError('Render cache view population changed')
        for name, view in result['views'].items():
            expected = expected_views[name]
            if view.get('frame') != expected.get('frame', 1) or view.get('resolution') != expected['resolution']:
                raise ValueError('Render cache frame or resolution changed')
            for key in ['image', 'mask']:
                if bool(expected.get(key)) != (key in view):
                    raise ValueError('Render cache artifact population changed')
                if key in view:
                    if view[key]['path'] != expected[key]:
                        raise ValueError('Render cache artifact path changed')
                    bound(view[key]['path'], view[key]['sha256'])
        if legacy_cache:
            print('Render cache verified against archived worker '+cached_worker+
                  '; original camera metadata preserved without reinterpretation', flush=True)
        return result
    write_json(output / 'request.json', request)
    with (output / 'worker.log').open('w') as log:
        completed = subprocess.run([str(BLENDER), '-b', '--factory-startup', '--disable-autoexec', '--threads', '2',
            '--python-exit-code', '1', '--python', str(ROOT / 'src/evaluator/continuous_render.py'), '--', str(output / 'request.json')],
            stdout=log, stderr=subprocess.STDOUT, timeout=900,
            env={**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2'})
    if completed.returncode: raise ValueError('Fixed-camera render failed; see worker.log')
    bound(scene['path'], scene['sha256'])
    return read_json(output / 'renders.json')
