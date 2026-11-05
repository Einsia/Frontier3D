"""Install a user-local Mesa EGL library and test Blender inside the L2 sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sysconfig
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / "third_party/mesa-headless"
MULTIARCH = sysconfig.get_config_var("MULTIARCH") or "x86_64-linux-gnu"


def mesa_library() -> Path:
    """Prefer the installed local runtime; never silently select NVIDIA EGL."""
    for directory in (RUNTIME / "usr/lib" / MULTIARCH,
                      Path("/usr/lib") / MULTIARCH, Path("/usr/lib64")):
        library = directory / "libEGL_mesa.so.0"
        if library.is_file():
            return library
    raise RuntimeError(
        "Mesa EGL is missing. Run ./.venv/bin/python -m harness.L2.headless --install --check "
        "on this Ubuntu/Debian host before rerunning L2 tasks.")


def graphics_identity() -> dict:
    library = mesa_library()
    return {"backend": "opengl", "egl_vendor": "mesa", "driver": "llvmpipe",
            "display": "surfaceless", "egl_library": str(library),
            "egl_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest()}


def install_mesa() -> Path:
    """Extract the EGL package matching the host's DRI driver, without sudo."""
    if platform.system() != "Linux" or not all(shutil.which(c) for c in ("apt-get", "dpkg-query", "dpkg-deb")):
        raise RuntimeError("Automatic installation requires Debian/Ubuntu with apt-get and dpkg")
    try:
        return mesa_library()
    except RuntimeError:
        pass
    if RUNTIME.exists():
        raise RuntimeError(f"Incomplete local Mesa runtime at {RUNTIME}; inspect it before reinstalling")
    version = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "libgl1-mesa-dri"],
                             check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    if not version:
        raise RuntimeError("Install the host libgl1-mesa-dri package first")
    RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mesa-download-") as downloads, \
            tempfile.TemporaryDirectory(prefix=".mesa-install-", dir=RUNTIME.parent) as staging:
        subprocess.run(["apt-get", "download", f"libegl-mesa0={version}"],
                       cwd=downloads, check=True, timeout=180)
        packages = list(Path(downloads).glob("*.deb"))
        if len(packages) != 1:
            raise RuntimeError("Expected exactly one Mesa EGL package")
        root = Path(staging) / "runtime"
        subprocess.run(["dpkg-deb", "--extract", str(packages[0]), str(root)], check=True, timeout=30)
        library = root / "usr/lib" / MULTIARCH / "libEGL_mesa.so.0"
        if not library.is_file():
            raise RuntimeError("Mesa package does not contain an EGL library for this architecture")
        dependencies = subprocess.run(["ldd", str(library)], capture_output=True, text=True, timeout=30)
        if dependencies.returncode or "not found" in dependencies.stdout:
            raise RuntimeError(f"Missing Mesa dependencies:\n{dependencies.stdout}\n{dependencies.stderr}")
        (root / "installation.json").write_text(json.dumps({
            "package": "libegl-mesa0", "version": version,
            "package_sha256": hashlib.sha256(packages[0].read_bytes()).hexdigest(),
            "source": "host APT repositories; version matched to libgl1-mesa-dri",
        }, indent=2) + "\n")
        root.rename(RUNTIME)
    return mesa_library()


def check(blender: Path | None, output_dir: Path, timeout: float = 120) -> dict:
    from PIL import Image
    from src.render.cli import _find_blender
    from .executor import run_process, sandbox_command

    identity = graphics_identity()
    root = output_dir.expanduser().resolve() / f"headless-check-{time.time_ns()}"
    workspace, output = root / "workspace", root / "output"
    workspace.mkdir(parents=True)
    output.mkdir()
    command = sandbox_command(Path(_find_blender(blender)), workspace, HERE / "headless_probe.py", [],
                              readonly=True, output=output)
    execution = run_process(command, cwd=workspace, logs=root / "logs", timeout=timeout)
    report = {"passed": False, "graphics": identity, "execution": execution.to_dict(), "directory": str(root)}
    try:
        if execution.status != "success":
            raise RuntimeError(f"Blender headless check failed: {execution.status}; see {root / 'logs'}")
        report["blender"] = json.loads((output / "probe.json").read_text())
        for name in ("eevee.png", "cycles.png"):
            with Image.open(output / name) as image:
                image.load()
                if image.size != (64, 64) or image.convert("RGB").getbbox() is None:
                    raise RuntimeError(f"Invalid probe image: {name}")
        report["passed"] = True
    except (OSError, ValueError, RuntimeError) as error:
        report["error"] = str(error)
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Extract missing Mesa EGL locally; no system changes")
    parser.add_argument("--check", action="store_true", help="Render EEVEE and Cycles CPU probes inside Bubblewrap")
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data/task_runs/l2_environment"))
    args = parser.parse_args(argv)
    try:
        if args.install:
            install_mesa()
        result = check(args.blender, args.output_dir) if args.check else graphics_identity()
        print(json.dumps(result, indent=2))
        return 0 if result.get("passed", True) else 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"[l2-headless] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
