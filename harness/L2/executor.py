"""L2 process ownership and Linux namespace isolation (no silent fallback)."""
from __future__ import annotations

import math
import os
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .headless import mesa_library


@dataclass(frozen=True)
class Execution:
    status: str
    return_code: int | None
    elapsed_seconds: float
    error_code: str | None = None

    def to_dict(self):
        return asdict(self)


def run_process(command: list[str], *, cwd: Path, logs: Path, timeout: float, cancel_event=None) -> Execution:
    """Write logs outside candidate mounts; terminate the entire process group."""
    if not math.isfinite(timeout) or timeout <= 0:
        return Execution("budget_exhausted", None, 0, "EXECUTOR_BUDGET_EXHAUSTED")
    logs.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (logs / "stdout.log").open("wb") as stdout, (logs / "stderr.log").open("wb") as stderr:
        try:
            process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                                       start_new_session=True, env={"PATH": "/usr/bin:/bin"})
        except OSError as error:
            stderr.write(str(error).encode())
            return Execution("unavailable", None, time.monotonic() - started, "EXECUTOR_UNAVAILABLE")
        timed_out = False
        cancelled = False
        try:
            if cancel_event is None:
                process.wait(timeout=timeout)
            else:
                while process.poll() is None:
                    if cancel_event.is_set():
                        cancelled = True
                        break
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        timed_out = True
                        break
                    try:
                        process.wait(timeout=min(.25, remaining))
                    except subprocess.TimeoutExpired:
                        pass
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            # Also removes descendants left behind after an apparently successful exit.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    status = "cancelled" if cancelled else "timeout" if timed_out else "success" if process.returncode == 0 else "process_error"
    return Execution(status, None if timed_out else process.returncode,
                     time.monotonic() - started,
                     None if status == "success" else f"EXECUTOR_{status.upper()}")


def sandbox_command(blender: Path, workspace: Path, worker: Path, args: list[str], *,
                    seed: int = 0, readonly: bool = False, output: Path | None = None,
                    extra_files: dict[str, Path] | None = None, threads: int = 8) -> list[str]:
    """Mount only runtime, allowlisted inputs and this seed's output directory.

    The task solution/reference bundle, repository, credentials, host /tmp and
    trusted logs/record are absent from the namespace. Inspection has read-only
    access to candidate files and a separate /audit output mount.
    """
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise RuntimeError("L2 execution requires bubblewrap; isolation is not bypassed")
    mesa = mesa_library()
    command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
               "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp/home",
               "--setenv", "TMPDIR", "/tmp", "--setenv", "PYTHONHASHSEED", str(seed),
               "--setenv", "THREEDBENCH_SEED", str(seed), "--setenv", "BENCHMARK_SEED", str(seed),
               "--setenv", "OMP_NUM_THREADS", str(threads),
               "--setenv", "LP_NUM_THREADS", str(threads),
               "--setenv", "LIBGL_ALWAYS_SOFTWARE", "1",
               "--setenv", "GALLIUM_DRIVER", "llvmpipe",
               "--setenv", "EGL_PLATFORM", "surfaceless",
               "--setenv", "__EGL_VENDOR_LIBRARY_FILENAMES", "/mesa_vendor.json",
               "--setenv", "MESA_SHADER_CACHE_DIR", "/tmp/mesa-cache"]
    for name in ("/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/fonts"):
        if Path(name).exists():
            command += ["--ro-bind", name, name]
    # Bundled Blender distributions carry Python, OCIO data and shared libraries.
    runtime = blender.resolve().parent
    command += ["--ro-bind", str(runtime), "/blender", "--proc", "/proc", "--dev", "/dev",
                "--ro-bind", str(mesa.parent), "/l2-mesa",
                "--ro-bind", str(Path(__file__).with_name("mesa_vendor.json")), "/mesa_vendor.json",
                "--tmpfs", "/tmp", "--dir", "/tmp/home",
                "--ro-bind" if readonly else "--bind", str(workspace.resolve()), "/work",
                "--ro-bind", str(worker.resolve()), "/runner.py"]
    if not readonly:
        command += ["--ro-bind", str(workspace / "solution.py"), "/work/solution.py"]
        if (workspace / "input").is_dir():
            command += ["--ro-bind", str(workspace / "input"), "/work/input"]
    if output is not None:
        command += ["--bind", str(output.resolve()), "/audit"]
    for target, source in (extra_files or {}).items():
        command += ["--ro-bind", str(source.resolve()), target]
    command += ["--chdir", "/work", f"/blender/{blender.name}", "--background", "--factory-startup",
                "--gpu-backend", "opengl",
                "--disable-autoexec", "-noaudio", "--threads", str(threads), "--python-exit-code", "1",
                "--python", "/runner.py", "--", *args]
    return command
