"""A minimal host filesystem view for the L2 model client and its tools."""
from pathlib import Path
import shutil


def native_codex(binary):
    path = Path(shutil.which(binary) or binary).resolve()
    def executable(candidate):
        if not candidate.is_file():
            return False
        with candidate.open('rb') as stream:
            return stream.read(4) == b'\x7fELF'
    if executable(path):
        return path
    # npm's JavaScript launcher selects this optional platform package.
    for base in (path.parent.parent/'node_modules/@openai', path.parent.parent/'vendor'):
        for pattern in ('**/bin/codex', '**/codex/codex'):
            for candidate in base.glob(pattern):
                if executable(candidate):
                    return candidate.resolve()
    raise RuntimeError('Cannot locate native Codex runtime for isolated L2 generation')


def generation_command(command, workspace, frozen_inputs, *, secret_path=None):
    bwrap = shutil.which('bwrap')
    if not bwrap:
        raise RuntimeError('L2 generation requires Bubblewrap')
    binary = native_codex(command[0])
    # The client needs API networking; its workspace-write tools retain Codex's
    # network-disabled sandbox. No host home, task library or repository is mounted.
    result = [bwrap, '--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts',
              '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--clearenv',
              '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/home/model',
              '--setenv', 'CODEX_HOME', '/home/model/.codex', '--setenv', 'SHELL', '/bin/sh']
    for name in ('/usr', '/bin', '/lib', '/lib64', '/etc/ld.so.cache', '/etc/ssl/certs', '/etc/resolv.conf', '/etc/hosts'):
        if Path(name).exists():
            result += ['--ro-bind', name, name]
    # The caller supplies only PATH and the client API key in env. Keeping the
    # credential in env avoids leaking it through bwrap argv and process listings.
    result += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/home', '--dir', '/home/model', '--dir', '/home/model/.codex',
               '--ro-bind', str(binary.parent.parent), '/codex-runtime', '--bind', str(workspace.resolve()), '/work']
    for name in ('input',):
        if (frozen_inputs/name).is_dir():
            result += ['--ro-bind', str((frozen_inputs/name).resolve()), '/work/'+name]
    for name in ('preview.py', 'query_scene.py', '.preview_policy.json'):
        result += ['--ro-bind', str(workspace/name), '/work/'+name]
    target = '/codex-runtime/'+binary.relative_to(binary.parent.parent).as_posix()
    if secret_path is not None:
        result += ['--ro-bind', str(Path(secret_path).resolve()), '/run/l2-codex-key',
                   '--ro-bind', str(Path(__file__).with_name('generation_launcher.py')), '/l2-launcher.py',
                   '--chdir', '/work', '/usr/bin/python3', '/l2-launcher.py', target]
    else:
        result += ['--chdir', '/work', target]
    args = [a.replace(str(workspace.resolve()), '/work') for a in command[1:]]
    args[-1:-1] = ['--config', 'approval_policy="never"', '--json']
    return result + args
