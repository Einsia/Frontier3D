"""Bounded file-reading operations for L1's existing killable compute worker.

Only paths and small options cross into the worker. Image decoding, source
syntax/JSON validation, copying and hashing happen there; no image pixels,
source contents or decoded candidate JSON are returned to the parent.
This does not bound the compute transport, path resolution or final reports.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from .l1_compute import run_compute
from .l1_failures import InspectionFailure


def _hash(path):
    with path.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
            raise ValueError('Missing, empty or nonregular file')
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('File changed while hashing')
    return {'path': str(path), 'sha256': value, 'bytes': after.st_size}


def _image(path):
    from PIL import Image
    with Image.open(path) as image:
        image.load()
        return {'size': list(image.size), 'mode': image.mode, 'format': image.format}


def execute_file_io(action: str, arguments: dict) -> dict:
    """Trusted fixed dispatch. Syntax/JSON checking never executes a source."""
    try:
        path = Path(arguments['path'])
        if action == 'hash':
            result = _hash(path)
        elif action == 'image_metadata':
            before = _hash(path)
            result = {**before, **_image(path)}
            if _hash(path) != before:
                raise ValueError('Image changed during decoding')
        elif action == 'stage_image':
            target = Path(arguments['target'])
            if target.exists() or target.is_symlink():
                raise ValueError('Refusing to overwrite a reference snapshot')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.reference-', delete=False) as stream:
                    temporary = Path(stream.name)
                before = _hash(path)
                shutil.copyfile(path, temporary)
                copied = _hash(temporary)
                if _hash(path) != before or copied['sha256'] != before['sha256']:
                    raise ValueError('Reference image changed during snapshot')
                metadata = _image(temporary)
                # Commit only successfully decoded frozen bytes. Existing
                # evidence cannot be replaced even under a target-name race.
                os.link(temporary, target)
                result = {**copied, **metadata, 'path': str(target), 'source': before}
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        elif action == 'validate_artifact':
            before = _hash(path)
            suffix = path.suffix.lower()
            metadata = {}
            if suffix == '.py':
                compile(path.read_bytes(), str(path), 'exec')
            elif suffix in {'.png', '.jpg', '.jpeg', '.webp'}:
                metadata = _image(path)
            elif suffix == '.json':
                json.loads(path.read_text(encoding='utf-8'))
            elif suffix in {'.txt', '.md', '.csv', '.toml'}:
                path.read_text(encoding='utf-8')
            else:
                raise ValueError(f'No artifact loader registered for {suffix!r}')
            if _hash(path) != before:
                raise ValueError('Artifact changed during validation')
            result = {**before, **metadata, 'loadable': True}
        else:
            raise ValueError('Unsupported L1 file operation')
        return {'protocol': 'l1-file-io-v1', 'status': 'ok', 'action': action, **result}
    except (OSError, ValueError, SyntaxError) as error:
        return {'protocol': 'l1-file-io-v1', 'status': 'failed', 'action': action,
                'error_type': type(error).__name__, 'reason': str(error)[:2048]}


def run_file_io(action: str, arguments: dict, *, output: Path, deadline: float | None, timeout=900.) -> dict:
    result = run_compute('file_io', {'action': action, 'arguments': arguments},
                         output=output, deadline=deadline, timeout=timeout)
    if result.get('protocol') != 'l1-file-io-v1' or result.get('action') != action:
        raise InspectionFailure('infrastructure_error', 'FILE_IO_PROTOCOL_ERROR', 'Unbound L1 file I/O result')
    if result.get('status') != 'ok':
        reason = result.get('reason', 'File operation unavailable')
        error_type = result.get('error_type')
        if error_type in {'SyntaxError', 'IndentationError', 'TabError'}:
            raise SyntaxError(reason)
        if error_type in {'ValueError', 'JSONDecodeError', 'UnicodeDecodeError'}:
            raise ValueError(reason)
        if error_type in {'FileNotFoundError', 'PermissionError', 'OSError', 'UnidentifiedImageError', 'IsADirectoryError'}:
            raise OSError(reason)
        raise InspectionFailure('infrastructure_error', 'FILE_IO_FAILED', reason)
    return result
