"""Render one retained image-task native file with the authored primary recipe."""
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    import bpy
    sys.path.insert(0, str(Path(__file__).parent))
    request = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    source = request['scene']; output = Path(request['output'])
    if digest(source['path']) != source['sha256']: raise ValueError('Native source changed')
    bpy.ops.wm.open_mainfile(filepath=source['path'], load_ui=False, use_scripts=False)
    # Resolve the saved frame in the fresh process before initializing the
    # render helper. Keep the authored camera, engine and sampling unchanged.
    bpy.context.scene.frame_set(request['frame'])
    from l1_image_blender import render_saved
    view = render_saved({'id': 'primary', 'frame': request['frame'],
                         'beauty_resolution': request['resolution']}, output)
    if digest(source['path']) != source['sha256']: raise ValueError('Native source changed during render')
    for name in ('image', 'mask'):
        view[name] = {'path': view[name], 'sha256': digest(view[name])}
    (output/'result.json').write_text(json.dumps({'scene': source, 'view': view,
        'worker_sha256': digest(__file__), 'request_sha256': digest(request['request_path']),
        'renderer_sha256': digest(Path(__file__).with_name('l1_image_blender.py')),
        'source_unchanged': True, 'candidate_code_executed': False}, indent=2))


if __name__ == '__main__':
    main()
