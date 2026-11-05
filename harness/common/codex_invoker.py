"""One Codex CLI attempt with process-group timeout handling."""
from __future__ import annotations
import os, signal, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from .errors import GENERATOR_EMPTY_OUTPUT, GENERATOR_PROCESS_ERROR, GENERATOR_TIMEOUT

@dataclass(frozen=True)
class Invocation:
    status: str
    error_code: str | None
    return_code: int | None
    elapsed_seconds: float
    stdout: str
    stderr: str
    output_path: str | None

def _kill_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
    else:
        process.kill()

def run_once(command: list[str], prompt: str, *, cwd: Path, output_path: Path, timeout: float, env: dict[str, str] | None = None) -> Invocation:
    started = time.monotonic()
    kwargs = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd, env=env or os.environ.copy())
    if os.name == "posix": kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError as error:
        return Invocation("process_error", GENERATOR_PROCESS_ERROR, None, time.monotonic()-started, "", str(error), None)
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        _kill_tree(process)
        out, err = error.stdout or "", error.stderr or ""
        if isinstance(out, bytes): out = out.decode(errors="replace")
        if isinstance(err, bytes): err = err.decode(errors="replace")
        return Invocation("timeout", GENERATOR_TIMEOUT, None, time.monotonic()-started, out, err, None)
    if process.returncode != 0:
        return Invocation("process_error", GENERATOR_PROCESS_ERROR, process.returncode, time.monotonic()-started, stdout, stderr, None)
    if not output_path.is_file() or not output_path.read_text(encoding="utf-8", errors="replace").strip():
        return Invocation("empty_output", GENERATOR_EMPTY_OUTPUT, process.returncode, time.monotonic()-started, stdout, stderr, None)
    return Invocation("success", None, process.returncode, time.monotonic()-started, stdout, stderr, str(output_path))
