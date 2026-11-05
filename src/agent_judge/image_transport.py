"""Lossless, pixel-bound image encoding for provider transport."""
from pathlib import Path
import shutil

from .protocol import digest,write_json
from .image_codec import encode_lossless_webp, encode_preview_webp


def prepare_images(work,attempt,manifest,mode):
    if mode=='original':return list(manifest['images']),None
    if mode not in {'lossless_webp', 'preview_webp'}:raise ValueError('Unknown image transport mode')
    folder=work/'_image_transport';folder.mkdir()
    archive=attempt/'image_attachments';archive.mkdir()
    rows=[];paths=[]
    for index,relative in enumerate(manifest['images']):
        source=work/relative;expected=manifest['sha256'][relative]
        if digest(source)!=expected:raise ValueError('Input image changed before encoding')
        target=folder/f'{index:03d}.webp'
        proof=(encode_preview_webp if mode=='preview_webp' else encode_lossless_webp)(source,target)
        provided=str(target.relative_to(work));paths.append(provided)
        shutil.copyfile(target,archive/target.name)
        rows.append({'evidence':relative,'source_sha256':expected,'provided':provided,
            'provided_sha256':digest(target),**proof,'archive':str((archive/target.name).relative_to(attempt))})
    record={'mode':mode,'resized':any(r.get('resized',False) for r in rows),
            'lossy':mode=='preview_webp','images':rows}
    write_json(attempt/'image_transport.json',record)
    return paths,record
