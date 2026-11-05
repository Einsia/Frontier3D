"""Blender-side bounded texture observation, separately from equivalence.

External images must be regular files inside caller-authorized resource roots.
Verified bytes are decoded from evaluator-owned copies, never reopened by path.
This boundary is not a replacement for host/process sandboxing.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

MAX_ENCODED_BYTES = 32 * 1024 * 1024
MAX_IMAGES = 32
MAX_PIXELS = 4_194_304


def _fields():
    spec = importlib.util.spec_from_file_location('l1_texture_fields', Path(__file__).with_name('l1_texture_fields.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TextureCapture:
    def __init__(self, directory, *, resource_roots):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.roots = [Path(root).resolve() for root in resource_roots]
        if not all(root.is_dir() for root in self.roots):
            raise ValueError('Texture resource root must be a directory')
        self.cache = {}
        self.decoder = _fields()

    def image(self, image):
        import bpy
        if image is None:
            raise ValueError('Image texture has no image')
        identity = image.as_pointer()
        if identity in self.cache:
            return self.cache[identity]
        if len(self.cache) >= MAX_IMAGES or image.source not in {'FILE', 'GENERATED'}:
            raise ValueError('Image count/source unsupported (sequences, tiled and movie inputs need adapters)')
        original = {'name': image.name, 'filepath': image.filepath, 'source': image.source}
        metadata = {'color_space': image.colorspace_settings.name, 'alpha_mode': image.alpha_mode}
        packed = image.packed_file
        if packed is not None:
            if packed.size > MAX_ENCODED_BYTES:
                raise ValueError('Packed image exceeds encoded byte limit')
            content = bytes(packed.data)
            origin = {**original, 'kind': 'packed'}
        elif image.source == 'FILE':
            authored = Path(bpy.path.abspath(image.filepath, library=image.library))
            if authored.is_symlink() or not any(authored.resolve().is_relative_to(root) for root in self.roots):
                raise ValueError('External image is outside authorized resource roots or is a symlink')
            if not authored.is_file() or authored.stat().st_size > MAX_ENCODED_BYTES:
                raise ValueError('External image missing or exceeds encoded byte limit')
            with authored.open('rb') as stream:
                content = stream.read(MAX_ENCODED_BYTES + 1)
            if len(content) > MAX_ENCODED_BYTES:
                raise ValueError('External image exceeds encoded byte limit')
            origin = {**original, 'kind': 'authorized_external', 'resolved_path': str(authored.resolve())}
        else:
            raise ValueError('Unpacked generated image persistence requires a separate adapter')
        encoded_sha = hashlib.sha256(content).hexdigest()
        origin['encoded_sha256'] = encoded_sha
        suffix = Path(image.filepath).suffix.lower()
        if suffix not in {'.png', '.jpg', '.jpeg', '.exr', '.hdr', '.tif', '.tiff', '.bmp', '.tga'}:
            suffix = {"OPEN_EXR": '.exr', "JPEG": '.jpg'}.get(image.file_format, '.png')
        encoded = self.directory / (encoded_sha + suffix)
        if not encoded.exists():
            encoded.write_bytes(content)
        if _digest(encoded) != encoded_sha:
            raise ValueError('Frozen image byte copy changed')
        decoded = bpy.data.images.load(str(encoded), check_existing=False)
        try:
            decoded.colorspace_settings.name = metadata['color_space']
            decoded.alpha_mode = metadata['alpha_mode']
            width, height = decoded.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ValueError('Invalid or excessive decoded image dimensions')
            pixels = np.empty(width * height * 4, dtype=np.float32)
            decoded.pixels.foreach_get(pixels)
            pixels = pixels.reshape(height, width, 4)
            metadata['image_is_float'] = bool(decoded.is_float)
            self.decoder.linearize_rgba(pixels, **metadata)  # validation, retain stored values for filtering
            identifier = hashlib.sha256((encoded_sha + json.dumps(metadata, sort_keys=True)).encode()).hexdigest()
            payload = self.directory / f'{identifier}.npz'
            np.savez_compressed(payload, stored_rgba=pixels)
            result = {'protocol': 'l1-texture-pixels-v1', 'status': 'ok', 'image_id': identifier,
                      'sampling': 'cycles_cpu_filter_then_decode_v1', 'path': str(payload), 'sha256': _digest(payload),
                      'size': [width, height], 'origin': {**origin, 'frozen_path': str(encoded)}, **metadata}
        finally:
            bpy.data.images.remove(decoded)
        self.cache[identity] = result
        return result

    def materials(self, materials, used_slots):
        observations = []
        for index in sorted(used_slots):
            if index >= len(materials) or materials[index] is None:
                continue
            material = materials[index]
            if not material.use_nodes or material.node_tree is None:
                continue
            stack = [node for node in material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL' and node.is_active_output]
            seen = set()
            while stack:
                node = stack.pop()
                if node.as_pointer() in seen:
                    continue
                seen.add(node.as_pointer())
                if len(seen) > 1024:
                    observations.append({'slot': index, 'status': 'not_measurable', 'reason': 'Reachable node count limit'})
                    break
                if node.type == 'TEX_IMAGE':
                    item = {'slot': index, 'node': node.name, 'interpolation': node.interpolation,
                            'extension': node.extension, 'projection': node.projection,
                            'alpha_output_linked_diagnostic': bool(node.outputs['Alpha'].is_linked)}
                    try:
                        item.update(status='ok', image=self.image(node.image))
                    except (OSError, RuntimeError, ValueError, TypeError) as error:
                        item.update(status='not_measurable', reason=str(error))
                    observations.append(item)
                if node.type == 'GROUP':
                    observations.append({'slot': index, 'node': node.name, 'status': 'not_measurable',
                                         'reason': 'Nested shader group dependency traversal not supported'})
                stack.extend(link.from_node for socket in node.inputs for link in socket.links)
        return {'protocol': 'l1-texture-observation-v1', 'observations': observations,
                'scope': 'reachable_image_dependencies_and_stored_pixels_only',
                'not_assessed': ['shader_field_expression_binding', 'world_surface_field_equivalence',
                                 'nested_shader_groups', 'external_resource_freezing_in_harness_baselines']}


def capture_uv_layers(bm, triangles, *, payload_path, geometry_sha256, default_layer):
    records = []
    for index, name in enumerate(bm.loops.layers.uv.keys()):
        if index >= 8:
            raise ValueError('UV layer observation limit exceeded')
        layer = bm.loops.layers.uv[name]
        values = np.asarray([[list(loop[layer].uv) for loop in triangle] for triangle in triangles], dtype=np.float64)
        if values.shape != (len(triangles), 3, 2) or not np.isfinite(values).all():
            raise ValueError('Invalid UV triangle coordinates')
        path = payload_path.with_name(payload_path.stem + f'-uv-{index}.npz')
        np.savez_compressed(path, triangle_uv=values)
        records.append({'name': name, 'path': str(path), 'sha256': _digest(path), 'geometry_sha256': geometry_sha256})
    return {'protocol': 'l1-surface-uv-v1', 'status': 'ok', 'default_layer': default_layer, 'layers': records}
