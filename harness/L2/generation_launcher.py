"""Inject the Codex API key from a read-only descriptor and exec the client."""
import os
from pathlib import Path
import sys

key = Path('/run/l2-codex-key').read_text(encoding='utf-8')
if not key or '\n' in key:
    raise SystemExit('Missing isolated Codex credential')
os.environ.clear()
os.environ.update(PATH='/usr/bin:/bin', HOME='/home/model', CODEX_HOME='/home/model/.codex',
                  SHELL='/bin/sh', CODEX_API_KEY=key)
os.execv(sys.argv[1], sys.argv[1:])
