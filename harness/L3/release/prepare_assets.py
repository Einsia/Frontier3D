"""Fetch or verify the frozen external L3 libraries; never refresh upstream catalogs."""

import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

LOCKS = Path(__file__).resolve().parent / "asset-locks"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def metadata():
    index = json.loads((LOCKS / "index.json").read_text())
    for name, expected in index["files"].items():
        if digest(LOCKS / name) != expected:
            raise ValueError("Asset lock changed: " + name)
    return {
        p.parent.name: json.loads(p.read_text()) for p in LOCKS.glob("*/manifest.json")
    }


def entries(manifest):
    return (
        [f for pack in manifest["packs"] for f in pack["files"]]
        if "packs" in manifest
        else manifest["files"]
    )


def checked_path(root, name):
    path = root / name
    if (
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or not path.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Unsafe asset path: " + name)
    return path


def valid(path, row):
    return (
        path.is_file()
        and path.stat().st_size == row["bytes"]
        and digest(path) == row["sha256"]
    )


def download(url, target, expected):
    """Stream to a temporary file, verify before replacing; failures retain no final bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=target.parent, suffix=".partial", delete=False
    ) as stream:
        partial = Path(stream.name)
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                shutil.copyfileobj(response, stream)
            stream.close()
            if digest(partial) != expected:
                raise ValueError("Downloaded asset hash differs: " + url)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


def archive_source(name, target, url, expected):
    bundled = LOCKS / "archives" / name
    if bundled.is_file():
        if digest(bundled) != expected:
            raise ValueError("Bundled archive hash differs: " + name)
        return bundled
    if not target.is_file() or digest(target) != expected:
        download(url, target, expected)
    return target


def extract_selected(archive, root, rows, prefix=""):
    with zipfile.ZipFile(archive) as zipped:
        for row in rows:
            target = checked_path(root, row["path"])
            if valid(target, row):
                continue
            member = row.get("archive_path") or row["path"].removeprefix(prefix)
            target.parent.mkdir(parents=True, exist_ok=True)
            with (
                zipped.open(member) as source,
                tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as out,
            ):
                partial = Path(out.name)
                try:
                    shutil.copyfileobj(source, out)
                    out.close()
                    if not valid(partial, row):
                        raise ValueError("Extracted asset differs: " + member)
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)


def fetch_library(name, manifest, root, workers):
    root.mkdir(parents=True, exist_ok=True)
    if "packs" in manifest:
        for pack in manifest["packs"]:
            if all(valid(checked_path(root, f["path"]), f) for f in pack["files"]):
                continue
            archive = archive_source(
                pack["id"] + ".zip",
                root / "archives" / (pack["id"] + ".zip"),
                pack["download_url"],
                pack["archive_sha256"],
            )
            extract_selected(archive, root, pack["files"], pack["id"] + "/")
    elif name.startswith("kenney-voxel"):
        if not all(valid(checked_path(root, f["path"]), f) for f in manifest["files"]):
            archive = archive_source(
                "voxel-pack.zip",
                root / "archives/voxel-pack.zip",
                manifest["archive_url"],
                manifest["archive_sha256"],
            )
            extract_selected(archive, root, manifest["files"])
    else:
        urls = {
            spec["path"]: spec["url"]
            for asset in manifest["assets"]
            for spec in asset["maps"].values()
        }

        def fetch_file(row):
            target = checked_path(root, row["path"])
            if not valid(target, row):
                download(urls[row["path"]], target, row["sha256"])

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(fetch_file, manifest["files"]))
    for source in (LOCKS / name).glob("*.json"):
        shutil.copyfile(source, root / source.name)


def verify_library(name, manifest, root):
    expected = digest(LOCKS / name / "manifest.json")
    if (
        not (root / "manifest.json").is_file()
        or digest(root / "manifest.json") != expected
    ):
        raise ValueError("Missing or different library manifest: " + name)
    for row in entries(manifest):
        if not valid(checked_path(root, row["path"]), row):
            raise ValueError("Missing or different asset: " + name + "/" + row["path"])
    return len(entries(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "verify", "locks"])
    parser.add_argument("--root", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    manifests = metadata()
    if args.command == "locks":
        print(
            json.dumps(
                {
                    name: {
                        "files": len(entries(m)),
                        "bytes": sum(f["bytes"] for f in entries(m)),
                    }
                    for name, m in manifests.items()
                },
                indent=2,
            )
        )
        return
    if not args.root or not 1 <= args.workers <= 32:
        parser.error("--root is required; --workers must be between 1 and 32")
    root = args.root.expanduser().resolve()
    for name, manifest in manifests.items():
        if args.command == "fetch":
            fetch_library(name, manifest, root / name, args.workers)
        print(
            name,
            verify_library(name, manifest, root / name),
            "files verified",
            flush=True,
        )


if __name__ == "__main__":
    main()
