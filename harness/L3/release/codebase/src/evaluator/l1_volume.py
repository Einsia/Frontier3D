"""Bounded, independent L1 intersection-volume/IoU inspection entry point."""

from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import time
from pathlib import Path

from .l1_failures import InspectionFailure
from .l1_surface import load_surface


def compare_volumes(
    left: dict,
    right: dict,
    *,
    trusted_root: Path,
    output: Path,
    blender: Path,
    timeout=120.0,
    grid_levels=(8, 16, 32),
    new_session: bool = True,
) -> dict:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Positive finite volume inspection timeout required")
    if (
        not grid_levels
        or any(type(n) is not int or not 2 <= n <= 64 for n in grid_levels)
        or list(grid_levels) != sorted(set(grid_levels))
    ):
        raise ValueError("Invalid volume grid refinement levels")
    if any(item.get("volume_reliable") is not True for item in (left, right)):
        return {"status": "not_measurable", "reason": "Unvalidated input solid volume"}
    for item in (left, right):
        load_surface(item["mesh_payload"], trusted_root)
    if not blender.is_file() or not os.access(blender, os.X_OK):
        raise InspectionFailure(
            "infrastructure_error", "BLENDER_UNAVAILABLE", str(blender)
        )
    output.mkdir(parents=True, exist_ok=False)
    manifest = output / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "left": left,
                "right": right,
                "trusted_root": str(trusted_root.resolve()),
                "grid_levels": list(grid_levels),
            },
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    result_path = output / "comparison.json"
    worker = Path(__file__).with_name("l1_boolean_blender.py")
    command = [
        str(blender.resolve()),
        "--background",
        "--factory-startup",
        "--disable-autoexec",
        "-noaudio",
        "--threads",
        "2",
        "--python-exit-code",
        "1",
        "--python",
        str(worker),
        "--",
        "--manifest",
        str(manifest.resolve()),
        "--output",
        str(result_path.resolve()),
    ]
    started = time.monotonic()
    with (
        (output / "worker.log").open("w", encoding="utf-8") as log,
        subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=new_session
        ) as process,
    ):
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise InspectionFailure(
                "infrastructure_error", "VOLUME_INSPECTION_TIMEOUT", str(timeout)
            ) from error
        finally:
            try:
                if new_session:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    # The enclosing trusted compute watchdog owns this group.
                    # Never send killpg to our own group from inside the job.
                    process.kill()
            except ProcessLookupError:
                pass
            process.wait()
    if returncode != 0:
        raise InspectionFailure(
            "infrastructure_error",
            "VOLUME_WORKER_ERROR",
            f"Exit {returncode}; see {output / 'worker.log'}",
        )
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or result.get("status") not in {
            "ok",
            "not_measurable",
        }:
            raise ValueError("Invalid volume worker result")
    except (OSError, ValueError) as error:
        raise InspectionFailure(
            "infrastructure_error", "VOLUME_WORKER_PROTOCOL_ERROR", str(error)
        ) from error
    result.update(
        elapsed_seconds=time.monotonic() - started,
        manifest_path=str(manifest),
        report_path=str(result_path),
    )
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
