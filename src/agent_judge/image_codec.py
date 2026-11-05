"""Pixel-preserving image encoding, usable by the isolated MCP process."""
import hashlib
from pathlib import Path


def encode_lossless_webp(source,target):
    from PIL import Image
    source,target=Path(source),Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(source) as image:
        if image.mode not in {'RGB','RGBA','L','LA','P'}:
            raise ValueError('Lossless transport requires an 8-bit source image')
        rgba=image.convert('RGBA');pixels=rgba.tobytes();size=list(rgba.size)
        rgba.save(target,'WEBP',lossless=True,quality=100,method=6,exact=True)
        with Image.open(target) as encoded:
            if list(encoded.size)!=size or encoded.convert('RGBA').tobytes()!=pixels:
                raise ValueError('Transport encoding changed source pixels')
    return {'rgba_sha256':hashlib.sha256(pixels).hexdigest(),'dimensions':size,
        'source_bytes':source.stat().st_size,'provided_bytes':target.stat().st_size,'identical_rgba':True}


def encode_preview_webp(source, target):
    """Bounded full-frame preview; original evidence stays archived unchanged."""
    from PIL import Image
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        rgba = image.convert('RGBA')
        original_size = list(rgba.size)
        rgba.thumbnail((768, 768), Image.Resampling.LANCZOS)
        rgba.save(target, 'WEBP', quality=85, method=4, exact=True)
    with Image.open(target) as encoded:
        pixels = encoded.convert('RGBA').tobytes()
        size = list(encoded.size)
    return {'rgba_sha256': hashlib.sha256(pixels).hexdigest(), 'dimensions': size,
            'source_dimensions': original_size, 'source_bytes': source.stat().st_size,
            'provided_bytes': target.stat().st_size, 'identical_rgba': False,
            'resized': original_size != size, 'lossy': True,
            'max_edge': 768, 'quality': 85, 'full_frame': True}
