"""Verify the source release inventory, hashes, local documentation and L3 bindings."""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/reference/release-manifest.json"
IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "runs",
    "artifacts",
    "logs",
    "third_party",
    ".config",
    ".native",
    ".private",
}


def release_files():
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(
            part in IGNORED_PARTS or part.endswith(".egg-info")
            for part in relative.parts
        ):
            continue
        if relative.parts[:2] in [("data", "task_runs"), ("data", "output_script")]:
            continue
        if (
            relative.parts[:5] == ("harness", "L3", "release", "codebase", "data")
            and len(relative.parts) > 5
            and relative.parts[5] == "l3"
        ):
            continue
        if (
            path == MANIFEST
            or path.name == ".env"
            or (path.name.startswith(".env.") and path.name != ".env.example")
        ):
            continue
        if path.suffix in {".pyc", ".pyo", ".blend1", ".blend2"}:
            continue
        if path.is_file() or path.is_symlink():
            yield path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_inventory_errors(root):
    """The L3 inventory must name real files after a task-directory migration."""
    errors=[]
    source=json.loads((root/'harness/L3/release/source-manifest.json').read_text())
    rows=source['files'];names=[r['path'] for r in rows]
    if len(rows)!=source['count'] or len(set(names))!=len(names):
        errors.append('L3 source inventory: count or duplicate path mismatch')
    for row in rows:
        name=row['path'];relative=Path(name);path=root/relative
        if (relative.is_absolute() or '..' in relative.parts or path.is_symlink()
                or not path.resolve().is_relative_to(root.resolve()) or not path.is_file()):
            errors.append('L3 source inventory: missing/unsafe path '+name)
        elif path.stat().st_size!=row['bytes'] or digest(path)!=row['sha256']:
            errors.append('L3 source inventory: file changed '+name)
    return errors


def doc_errors(files):
    errors = []
    for path in files:
        if path.suffix != ".md":
            continue
        for target in re.findall(r"\]\(([^\s)]+)", path.read_text()):
            url = urlsplit(target.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (path.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                errors.append(
                    f"{path.relative_to(ROOT)}: unresolved local link {target}"
                )
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Rebuild inventory after reviewed release changes",
    )
    args = parser.parse_args()
    files = sorted(release_files())
    errors = [str(p.relative_to(ROOT)) + ": symlink" for p in files if p.is_symlink()]
    errors.extend(doc_errors(files))
    try:
        errors.extend(source_inventory_errors(ROOT))
    except (OSError,ValueError,KeyError) as error:
        errors.append('L3 source inventory: '+str(error))
    attribution_spec = importlib.util.spec_from_file_location(
        "release_attribution_check", ROOT / "scripts/verify_attribution.py"
    )
    attribution_module = importlib.util.module_from_spec(attribution_spec)
    attribution_spec.loader.exec_module(attribution_module)
    try:
        print("Attribution:", json.dumps(attribution_module.verify(ROOT)))
    except (OSError, ValueError, KeyError) as error:
        errors.append("Attribution: " + str(error))
    spec = importlib.util.spec_from_file_location(
        "l3_release_resources", ROOT / "harness/L3/release/check_resources.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        print("L3 resources:", json.dumps(module.verify_resources()))
    except (OSError, ValueError, KeyError) as error:
        errors.append("L3 resources: " + str(error))
    if args.update_manifest and not errors:
        MANIFEST.write_text(
            json.dumps(
                {
                    "version": 1,
                    "files": {p.relative_to(ROOT).as_posix(): digest(p) for p in files},
                },
                indent=2,
            )
            + "\n"
        )
    manifest = json.loads(MANIFEST.read_text())["files"]
    actual = {p.relative_to(ROOT).as_posix() for p in files}
    for name in sorted(actual - set(manifest)):
        errors.append(name + ": unmanifested release file")
    for name, expected in manifest.items():
        path = ROOT / name
        if path.is_symlink() or not path.is_file():
            errors.append(name + ": missing or symlink")
        elif digest(path) != expected:
            errors.append(name + ": SHA-256 differs")
    for error in errors:
        print(error, file=sys.stderr)
    print(f"Verified {len(manifest)} packaged files; {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
