"""Stage local task inputs without organizer source attribution."""
import json
from pathlib import Path
import re
import shutil

_NOTICE = re.compile(r'(?:credits?|creadits?|licenses?|sources?|provenance|attribution)(?:\.(?:txt|md|json))?', re.I)


def public_references(refs):
    result = {k: refs[k] for k in ('schema', 'input_mode', 'geometry_scope', 'hud_and_people') if k in refs}
    result['images'] = [{k: image[k] for k in ('id', 'path', 'sha256', 'width', 'height') if k in image}
                        for image in refs['images']]
    return result


def reference_guide(refs):
    return ('# Visual references\n\nUse the supplied local images as the visual target. '
            'Complete unseen spaces coherently according to the task brief.\n\n' +
            ''.join(f"- `{image['path']}`: {image['width']} × {image['height']} pixels.\n"
                    for image in refs['images']))


def stage_public_inputs(source, destination):
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.rglob('*'):
        relative = path.relative_to(source)
        if path.is_symlink():
            raise ValueError('Symlink in public L3 inputs: ' + str(relative))
        if any(part.casefold() in {'attribution', 'solution', 'harness', 'verifier'} for part in relative.parts):
            continue
        if not path.is_file() or _NOTICE.fullmatch(path.name) or path.name == 'REFERENCES.md':
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.name == 'references.json':
            refs = public_references(json.loads(path.read_text()))
            target.write_text(json.dumps(refs, ensure_ascii=False, indent=2) + '\n')
            target.with_name('REFERENCES.md').write_text(reference_guide(refs))
        else:
            shutil.copy2(path, target)
