"""Trusted Blender image-snapshot worker with hash-bound JSON request."""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--request', type=Path, required=True)
parser.add_argument('--result', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
content = args.request.read_bytes()
if len(content) > 1024 * 1024:
    raise ValueError('Image snapshot request size limit')
request = json.loads(content)
if request['protocol'] != 'l1-image-dependency-snapshot-v1':
    raise ValueError('Invalid image snapshot request protocol')
spec = importlib.util.spec_from_file_location('l1_resources', Path(__file__).with_name('l1_resources.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if module.file_hash(request['source']) != request['source_sha256']:
    raise ValueError('Scene changed before resource snapshot')
if 'glb_source' in request and module.file_hash(request['glb_source']) != request['glb_source_sha256']:
    raise ValueError('GLB changed before resource snapshot')
result = module.snapshot_native_images(request['source'], request['output'],
                                      authority=request['authority'], frames=tuple(request['frames']),
                                      glb_source=request.get('glb_source'))
result.setdefault('source_sha256', request['source_sha256'])
result['request_sha256'] = hashlib.sha256(content).hexdigest()
args.result.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
