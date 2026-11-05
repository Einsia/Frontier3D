"""Use directory descriptors when communicating with a live, untrusted workspace."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import uuid

from src.evaluator.spec import relative_path


@contextmanager
def parent_fd(root, name):
    parts = Path(relative_path(name)).parts
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor, parts[-1]
    finally:
        os.close(descriptor)


def read_bytes(root, name, *, max_bytes=16*1024*1024):
    with parent_fd(root, name) as (parent, leaf):
        descriptor = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= max_bytes:
                raise ValueError('Unsafe/oversized workspace file: '+name)
            data = stream.read(max_bytes+1)
            if len(data) > max_bytes:
                raise ValueError('Workspace file grew past its size limit')
            return data


def publish(root, name, data):
    """Replace a directory entry atomically, never follow its previous target."""
    with parent_fd(root, name) as (parent, leaf):
        temporary = '.harness-'+uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
            os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
