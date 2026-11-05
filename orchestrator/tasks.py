"""L1 instance manifests. Public staging never traverses private solutions."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import tomllib

PROJECT = Path(__file__).resolve().parents[1]
TASKS = PROJECT / 'data/3dbench/tasks'
L2_ID = re.compile(r'L2/(Brief2Scene|Reference2Scene|Reference2Scene-RealPhoto|SceneEdit)/task_L2_([A-Za-z0-9-]+?)[_-]([0-9]{3})\Z')
ID = re.compile(r'L1/(Text2Code|Image2Code|Image2Code-SingleView|CodeEdit)/task_L1_([A-Za-z0-9-]+)_([0-9]{3})\Z')


def relative(value: str) -> Path:
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid relative task path')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {'', '.', '..'} for x in value.split('/')):
        raise ValueError('Unsafe relative task path')
    return Path(*p.parts)


def regular(root: Path, value: str) -> Path:
    if root.is_symlink():
        raise ValueError('Symlink root is not allowed')
    p = root
    for part in relative(value).parts:
        p = p / part
        if p.is_symlink():
            raise ValueError(f'Symlink is not allowed: {value}')
    if not stat.S_ISREG(p.stat().st_mode):
        raise ValueError(f'Not a regular file: {value}')
    return p


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


@dataclass(frozen=True)
class Task:
    root: Path
    manifest: dict

    @property
    def id(self):
        return self.manifest['id']

    @property
    def category(self):
        return self.manifest['category']

    @property
    def artifacts(self):
        return tuple(str(relative(p).relative_to('output')) for p in self.manifest['submission_files'])

    def stage(self, workspace: Path):
        from src.generator.public_inputs import require_public_input
        for name in self.manifest['environment_files']:
            require_public_input(name)
        workspace.mkdir(parents=True, exist_ok=False)
        (workspace / 'input').mkdir()
        (workspace / 'output').mkdir()
        shutil.copyfile(regular(self.root, self.manifest['instruction']), workspace / 'instruction.md')
        for name in self.manifest['environment_files']:
            source = regular(self.root / self.manifest['environment'], name)
            target = workspace / relative(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        return {str(p.relative_to(workspace)): sha256(p) for p in workspace.rglob('*') if p.is_file()}


def load_task(task_id: str, tasks_root: Path = TASKS, *, require_harness=True) -> Task:
    level = 2 if task_id.startswith('L2/') else 1
    match = (L2_ID if level == 2 else ID).fullmatch(task_id)
    if not match or match[1] != match[2]:
        raise ValueError('Expected a matching L1/L2 category and task instance ID')
    root = tasks_root.resolve() / task_id
    for directory in (root.parent.parent, root.parent, root):
        if directory.is_symlink():
            raise ValueError('Symlink task directory is not allowed')
    manifest = tomllib.loads(regular(root, 'task.toml').read_text())
    if manifest.get('id') != task_id or manifest.get('level') != level or manifest.get('category') != match[1]:
        raise ValueError('Task manifest identity mismatch')
    if manifest.get('submission_root') != 'output' or manifest.get('entrypoint') != 'output/solution.py':
        raise ValueError('Unsupported output/entrypoint contract')
    for field in ('instruction', 'environment', 'harness'):
        relative(manifest[field])
    regular(root, manifest['instruction'])
    inputs = manifest.get('environment_files')
    if not isinstance(inputs, list) or len(set(inputs)) != len(inputs):
        raise ValueError('Invalid input allowlist')
    for name in inputs:
        from src.generator.public_inputs import require_public_input
        require_public_input(name)
        if relative(name).parts[0] != 'input':
            raise ValueError('Model-visible files must be under input/')
        regular(root / manifest['environment'], name)
    required = manifest.get('submission_files', [])
    minimum = {'output/solution.py', 'output/scene.blend', 'output/README.md'} | ({'output/scene.glb'} if level == 1 else {'output/main.png', 'output/alternate.png'})
    if not isinstance(required, list) or len(set(required)) != len(required) or not minimum <= set(required):
        raise ValueError('Required outputs missing from contract')
    for name in required:
        if relative(name).parts[0] != 'output':
            raise ValueError('Deliverables must be under output/')
    if require_harness:
        if manifest.get('harness_status') not in {'mvp', 'implemented'}:
            raise ValueError(f'Case harness not integrated: {task_id}')
        regular(root, manifest['harness']+'/evaluate.py')
        regular(root, manifest['harness']+'/eval_spec.json')
    return Task(root, manifest)


def inventory(tasks_root=TASKS, level=1):
    if level not in (1, 2):
        raise ValueError('Supported inventory levels are 1 and 2')
    for path in sorted((tasks_root / f'L{level}').glob('*/*/task.toml')):
        raw = tomllib.loads(path.read_text())
        yield {'task_id': raw['id'], 'category': raw['category'], 'harness_status': raw.get('harness_status', 'not_implemented')}
