"""Organizer-only Poly Haven snapshot preparation; never run inside a trial.

Freeze catalog -> resolve URLs/checksums -> download -> verify. A partial
download is not a usable pack. This module deliberately has no scene assets.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.request

USER_AGENT = '3DBench-AssetPreparation/1.0 (academic offline material snapshot)'
CHANNELS = {'basecolor': ('Diffuse', 'diff', 'diff_png', 'col1', 'col_01', 'col_1', 'coll1'),
            'normal': ('nor_dx', 'normal_dx', 'nor_gl'),
            'roughness': ('Rough', 'rough'), 'metallic': ('Metal', 'metal'),
            'ao': ('AO', 'ao'), 'opacity': ('Opacity', 'alpha'),
            'mask': ('Mask',), 'height': ('Displacement',)}

def digest(path, algorithm='sha256'):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, algorithm).hexdigest()

def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.partial')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)

def get(url):
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

def select_maps(files, resolution):
    selected = {}
    for channel, names in CHANNELS.items():
        for name in names:
            formats = files.get(name, {}).get(resolution, {})
            # Lossless normals/scalar maps; JPEG basecolor is the compact profile.
            order = ('jpg', 'png') if channel == 'basecolor' else ('png', 'jpg')
            fmt = next((f for f in order if f in formats), None)
            if fmt:
                selected[channel] = dict(formats[fmt], format=fmt, source_channel=name)
                if channel == 'normal':
                    selected[channel]['normal_convention'] = 'OpenGL' if name == 'nor_gl' else 'DirectX'
                break
    missing = {'basecolor', 'normal', 'roughness'} - selected.keys()
    if missing:
        raise ValueError(f'missing required maps: {sorted(missing)}')
    return selected

def plan(catalog_path, output, resolution, workers):
    catalog = json.loads(catalog_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    def resolve(item):
        asset_id, metadata = item
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', asset_id):
            raise ValueError('unsafe asset ID')
        cache = output / 'metadata' / f'{asset_id}.json'
        if not cache.exists():
            write_json(cache, json.loads(get('https://api.polyhaven.com/files/' + asset_id)))
            time.sleep(0.25)
        maps = select_maps(json.loads(cache.read_text()), resolution)
        for channel, spec in maps.items():
            spec['path'] = f'textures/{asset_id}/{channel}.{spec["format"]}'
        return {'id': asset_id, 'name': metadata['name'], 'tags': metadata.get('tags', []),
                'categories': metadata.get('categories', []), 'authors': metadata.get('authors', {}),
                'dimensions_source': metadata.get('dimensions'), 'license': 'CC0-1.0',
                'source': f'https://polyhaven.com/a/{asset_id}', 'maps': maps}
    assets, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(resolve, item): item[0] for item in sorted(catalog.items())}
        for index, future in enumerate(as_completed(pending), 1):
            try:
                assets.append(future.result())
            except Exception as error:
                errors.append({'id': pending[future], 'error': str(error)})
            if index % 50 == 0:
                print(f'resolved {index}/{len(pending)}', flush=True)
    result = {'schema_version': 1, 'provider': 'Poly Haven', 'credit': 'Powered by Poly Haven',
              'license_url': 'https://polyhaven.com/license', 'resolution': resolution,
              'catalog_sha256': digest(catalog_path), 'source_asset_count': len(catalog),
              'normal_convention': 'per-map metadata', 'profile': 'jpg-color-lossless-data',
              'assets': sorted(assets, key=lambda x: x['id']), 'errors': errors}
    write_json(output/'plan.json', result)
    print(json.dumps({'assets':len(assets), 'errors':errors,
                      'bytes':sum(s['size'] for a in assets for s in a['maps'].values())}), flush=True)
    if errors:
        raise RuntimeError('incomplete plan; resolve errors before publishing')

def fetch(plan_path, output, workers):
    plan_data = json.loads(plan_path.read_text())
    if plan_data['errors']:
        raise ValueError('plan contains unresolved assets')
    specs = [s for a in plan_data['assets'] for s in a['maps'].values()]
    def download(spec):
        target = output / spec['path']
        target.resolve().relative_to(output.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.is_file() and target.stat().st_size == spec['size']
                and digest(target, 'md5') == spec['md5']):
            blob = get(spec['url'])
            if len(blob) != spec['size'] or hashlib.md5(blob).hexdigest() != spec['md5']:
                raise ValueError('upstream size/checksum mismatch: ' + spec['path'])
            temp = target.with_suffix(target.suffix+'.partial')
            temp.write_bytes(blob)
            temp.replace(target)
        return {'path': spec['path'], 'sha256': digest(target), 'bytes': target.stat().st_size}
    files, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(download, spec): spec['path'] for spec in specs}
        for index, future in enumerate(as_completed(pending), 1):
            try:
                files.append(future.result())
            except Exception as error:
                errors.append({'path': pending[future], 'error': str(error)})
            if index % 100 == 0:
                print(f'downloaded/verified {index}/{len(pending)}', flush=True)
    result = dict(plan_data, status='complete' if not errors else 'incomplete',
                  plan_sha256=digest(plan_path), files=sorted(files,key=lambda x:x['path']),
                  download_errors=errors)
    write_json(output/'manifest.json', result)
    print(json.dumps({'status':result['status'], 'files':len(files), 'errors':errors}), flush=True)
    if errors:
        raise RuntimeError('incomplete download; rerun against the same plan')

def verify(manifest_path):
    data = json.loads(manifest_path.read_text())
    if data['status'] != 'complete' or data.get('errors') or data.get('download_errors'):
        raise ValueError('pack is incomplete')
    planned = {s['path'] for a in data['assets'] for s in a['maps'].values()}
    observed = [f['path'] for f in data['files']]
    if set(observed) != planned or len(observed) != len(planned):
        raise ValueError('manifest file coverage differs from planned material maps')
    for item in data['files']:
        path = manifest_path.parent/item['path']
        path.resolve().relative_to(manifest_path.parent.resolve())
        if path.is_symlink() or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('modified or missing file: ' + item['path'])
    print(json.dumps({'status':'verified','materials':len(data['assets']), 'files':len(observed),
                      'manifest_sha256':digest(manifest_path)}))

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan','fetch','verify'])
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--resolution',choices=['1k','2k','4k'],default='2k')
    parser.add_argument('--workers',type=int,choices=range(1,9),default=2)
    args=parser.parse_args()
    if args.action == 'verify': verify(args.input)
    elif args.output is None: parser.error('--output is required for plan/fetch')
    elif args.action == 'plan': plan(args.input,args.output,args.resolution,args.workers)
    else: fetch(args.input,args.output,args.workers)
