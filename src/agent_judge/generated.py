"""Validate persisted tool evidence for scoring and offline replay."""

from pathlib import Path

from .protocol import digest, read_json


def verify_tool_image_transport(ledger,generated):
    count=0
    for call in ledger['calls']:
        proof=call.get('image_transport')
        if not proof:continue
        from PIL import Image
        import hashlib
        original=generated/proof['source_evidence'];wire=generated/proof['archive']
        if (proof['mode'] not in {'lossless_webp','preview_webp'}
                or not wire.resolve().is_relative_to(generated.resolve())
                or not original.resolve().is_relative_to(generated.resolve())
                or ledger['sha256'].get(proof['source_evidence'])!=proof['source_sha256']
                or digest(original)!=proof['source_sha256'] or digest(wire)!=proof['provided_sha256']):
            raise ValueError('Invalid tool image transport binding')
        if proof['mode']=='preview_webp':
            # Re-encode from the bound original rather than trusting claimed
            # dimensions or a matching hash of an arbitrary replacement image.
            import tempfile
            from .image_codec import encode_preview_webp
            with tempfile.TemporaryDirectory(prefix='judge-preview-verify-') as temporary:
                replay=Path(temporary)/'preview.webp'
                expected=encode_preview_webp(original,replay)
                if (any(proof.get(k)!=v for k,v in expected.items())
                        or digest(replay)!=proof['provided_sha256']):
                    raise ValueError('Tool preview differs from its bound original')
            count+=1
            continue
        if (proof['lossy'] is not False or proof['resized'] is not False
                or proof['identical_rgba'] is not True):
            raise ValueError('Invalid lossless transport declaration')
        with Image.open(original) as a,Image.open(wire) as b:
            pixels=a.convert('RGBA').tobytes()
            if a.size!=b.size or list(a.size)!=proof['dimensions'] or pixels!=b.convert('RGBA').tobytes() or hashlib.sha256(pixels).hexdigest()!=proof['rgba_sha256']:
                raise ValueError('Tool image transport changed source pixels')
        count+=1
    return count


def verified_evidence(packet_manifest, generated: Path | None = None, *, require_render=True):
    paths = list(packet_manifest["evidence"])
    if generated is None:
        if packet_manifest["mode"] == "interactive":
            raise ValueError(
                "Interactive scoring requires --generated from the accepted attempt"
            )
        return paths
    ledger = read_json(generated / "manifest.json")
    verify_tool_image_transport(ledger,generated)
    expected_sources = {
        p: s
        for p, s in packet_manifest["sha256"].items()
        if p.lower().endswith(".blend")
    }
    if ledger["sources"] != expected_sources:
        raise ValueError("Generated evidence refers to a different native input set")
    if ledger["worker_sha256"] != packet_manifest["interactive_worker_sha256"]:
        raise ValueError("Blender worker version differs from frozen packet")
    for source, sha in ledger["sources"].items():
        if packet_manifest["sha256"].get(source) != sha:
            raise ValueError("Generated evidence refers to a different native input")
    successful = {
        p for c in ledger["calls"] if c["status"] == "success" for p in c["files"]
    }
    for path, sha in ledger["sha256"].items():
        file = generated / path
        if (
            path not in packet_manifest["generated_slots"]
            or path not in successful
            or file.is_symlink()
            or not file.resolve().is_relative_to(generated.resolve())
            or digest(file) != sha
        ):
            raise ValueError("Invalid or modified generated evidence")
        paths.append(path)
    required_roles = {p.split("/")[0] for p in ledger["sources"]}
    rendered_roles = {
        c["arguments"]["scene"].split("/")[0]
        for c in ledger["calls"]
        if c["status"] == "success" and c["tool"] == "render_view"
    }
    if require_render and required_roles - rendered_roles:
        raise ValueError("Interactive judge must render each role with a native scene")
    return paths
