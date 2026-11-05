"""Inspect unpacked Blender dependencies without executing candidate code."""
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    import bpy
    request_path = Path(sys.argv[sys.argv.index('--') + 1])
    request = json.loads(request_path.read_text())
    source = Path(request['scene']['path'])
    if digest(source) != request['scene']['sha256']:
        raise ValueError('Scene binding changed')
    bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    # Blender startup assets may leave a brush library in every saved file.
    # Follow datablock users from the scene; editor-only libraries do not
    # participate in scene delivery and must not invalidate a candidate.
    users = bpy.data.user_map()
    used = {bpy.context.scene}
    while True:
        expanded = used | {block for block, owners in users.items() if owners & used}
        if expanded == used:
            break
        used = expanded
    unused_libraries = {library.filepath for library in bpy.data.libraries
                        if not any(block.library == library for block in used)}
    used_paths = {getattr(block, 'filepath', '') for block in used}
    used_paths.update(block.library.filepath for block in used if block.library)
    brush_assets = set()
    settings = bpy.context.scene.tool_settings
    for prop in settings.bl_rna.properties:
        if prop.type != 'POINTER':
            continue
        paint = getattr(settings, prop.identifier, None)
        reference = getattr(paint, 'brush_asset_reference', None)
        if reference and not reference.asset_library_identifier:
            relative = reference.relative_asset_identifier
            if '/Brush/' in relative:
                brush_assets.add(relative.split('/Brush/')[0])
    rows = []
    ignored = []
    for raw in bpy.utils.blend_paths(absolute=False, packed=False, local=False):
        if (raw not in used_paths and any(raw.endswith('/datafiles/assets/' + asset) for asset in brush_assets)):
            ignored.append({'stored_path': raw, 'reason': 'Builtin editor brush asset reference; no scene datablock uses this path'})
            continue
        if raw in unused_libraries:
            ignored.append({'stored_path': raw, 'reason': 'Library has no scene-reachable datablock users'})
            continue
        resolved = Path(bpy.path.abspath(raw)).resolve()
        portable = raw.startswith('//') and resolved.is_relative_to(source.parent / 'assets')
        if '<UDIM>' in raw or '#' in raw:
            status = 'not_measurable'
        elif not portable or not resolved.is_file():
            status = 'failed'
        else:
            status = 'passed'
        rows.append({'stored_path': raw, 'resolved_path': str(resolved), 'measurement_status': status,
                     'sha256': digest(resolved) if status == 'passed' else None})
    if digest(source) != request['scene']['sha256']:
        raise ValueError('Inspector changed source')
    result = {'scene': request['scene'], 'unpacked_dependencies': rows,
              'ignored_unused_libraries': ignored,
              'scope': 'All external paths reported by Blender, excluding packed data; portable output/assets required',
              'source_unchanged': True, 'candidate_code_executed': False,
              'request_sha256': digest(request_path), 'worker_sha256': digest(__file__)}
    Path(request['output']).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
