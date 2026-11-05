"""Real Blender import fingerprint for resource repackaging, not task scoring."""
import hashlib
import json
import sys
from pathlib import Path

import bpy

source, output = map(Path, sys.argv[sys.argv.index('--') + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(source))
objects = []
for obj in bpy.context.scene.objects:
    if obj.type == 'MESH':
        objects.append({'vertices': [list(obj.matrix_world @ v.co) for v in obj.data.vertices],
                        'polygons': [list(p.vertices) for p in obj.data.polygons],
                        'uv': [list(loop.uv) for loop in obj.data.uv_layers.active.data]})
images = []
for image in bpy.data.images:
    if image.source in {'FILE', 'GENERATED'}:
        # Blender loads some imported images lazily. has_data before pixel
        # access would silently omit every image and prove nothing about it.
        pixels = list(image.pixels)
        if not pixels:
            raise ValueError('Imported GLB image has no readable pixels: ' + image.name)
        images.append({'size': list(image.size), 'colorspace': image.colorspace_settings.name,
                       'pixels_sha256': hashlib.sha256(json.dumps(pixels).encode()).hexdigest()})
output.write_text(json.dumps({'objects': objects, 'images': sorted(images, key=lambda x: x['pixels_sha256'])}, indent=2))
