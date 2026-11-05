"""Trusted native-image and core GLB dependency snapshots, not a sandbox.

The original .blend is never modified. Render-reachable images in declared
frames are frozen, authorized external bytes packed into a derived .blend,
and a provenance record binds raw input, authority, bytes and derived output.
Standard GLB buffer/image URI assets are frozen separately without reindexing.
Other dependencies (libraries, caches, extension-defined resources) need adapters.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
import os
import re
import shutil
import struct
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

PROTOCOL = 'l1-image-dependency-snapshot-v1'
AUTHORITY_PROTOCOL = 'l1-resource-authority-v1'
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_IMAGES = 32
MAX_NODES = 4096
MAX_GLB_BYTES = 512 * 1024 * 1024
MAX_GLB_JSON_BYTES = 192 * 1024 * 1024
MAX_GLB_RESOURCES = 128


def _integer(value, minimum=0):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value) or value != int(value) or value < minimum):
        raise ValueError('Invalid GLB integer field')
    return int(value)


def _glb_parts(source):
    """Read bounded core GLB chunks; opaque extension chunk handling is separate."""
    source = Path(source)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != '.glb':
        raise ValueError('Invalid GLB source')
    size = source.stat().st_size
    if not 20 <= size <= MAX_GLB_BYTES:
        raise ValueError('GLB size outside snapshot limits')
    def constant(value):
        raise ValueError('Non-finite JSON number in GLB: ' + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite GLB JSON float')
        return result
    with source.open('rb') as stream:
        if struct.unpack('<4sII', stream.read(12)) != (b'glTF', 2, size):
            raise ValueError('Invalid GLB header/length')
        length, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A or length % 4 or not 0 < length <= min(MAX_GLB_JSON_BYTES, size - 20):
            raise ValueError('Invalid or oversized GLB JSON chunk')
        document = json.loads(stream.read(length), parse_constant=constant, parse_float=finite_float)
        if not isinstance(document, dict) or not isinstance(document.get('asset'), dict) or document['asset'].get('version') != '2.0':
            raise ValueError('Invalid GLB asset metadata')
        tail = stream.read(MAX_GLB_BYTES + 1)
    binary = None
    if tail:
        if len(tail) < 8:
            raise ValueError('Truncated GLB BIN header')
        length, kind = struct.unpack('<II', tail[:8])
        if kind != 0x004E4942 or length % 4 or length != len(tail) - 8:
            raise ValueError('Unknown, duplicate or invalid GLB chunks require an adapter')
        binary = memoryview(tail)[8:]
    return document, tail, binary


def _image_mime(content):
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    raise ValueError('GLB image encoding requires a supported PNG/JPEG signature')


def _data_uri(uri, category):
    header, separator, encoded = uri.partition(',')
    allowed = {'data:application/octet-stream;base64', 'data:application/gltf-buffer;base64'} if category == 'buffers' else {
        'data:image/png;base64', 'data:image/jpeg;base64'}
    if not separator or header not in allowed or len(encoded) > ((MAX_TOTAL_BYTES + 2) // 3) * 4:
        raise ValueError('Unsupported or oversized GLB data URI')
    content = base64.b64decode(encoded, validate=True)
    if not content or len(content) > MAX_TOTAL_BYTES:
        raise ValueError('Empty or oversized GLB data URI')
    mime = header[5:-7]
    if category == 'images' and _image_mime(content) != mime:
        raise ValueError('GLB data URI media type differs from image bytes')
    return content, mime


def _glb_external_path(uri, authority):
    if not isinstance(uri, str) or not uri or len(uri) > 8192 or any(ord(c) <= 32 for c in uri) or '\\' in uri:
        raise ValueError('Invalid GLB external URI')
    if re.search(r'%(?![0-9A-Fa-f]{2})', uri):
        raise ValueError('Malformed GLB URI percent encoding')
    parsed = urlsplit(uri)
    # urlsplit loses the distinction between an absent delimiter and an empty
    # query/fragment. Never silently drop a raw '?'/'#' and read another asset;
    # literal filename characters must arrive percent-encoded instead.
    if parsed.scheme not in {'', 'file'} or parsed.netloc or '?' in uri or '#' in uri:
        raise ValueError('Network or parameterized GLB URI is not authorized')
    decoded = unquote(parsed.path, encoding='utf-8', errors='strict')
    if not decoded or '\\' in decoded or any(ord(c) < 32 for c in decoded):
        raise ValueError('Invalid decoded GLB URI path')
    path = Path(decoded)
    if parsed.scheme == 'file' and not path.is_absolute():
        raise ValueError('Relative file-scheme URI unsupported')
    # Native and GLB task deliverables share the same original directory. Do
    # not resolve relative to the relocated frozen copy of scene.glb.
    if not path.is_absolute():
        path = Path(authority['origin_scene']).parent / path
    return Path(os.path.abspath(path))


def snapshot_glb_resources(source, target, *, authority):
    """Freeze standard buffer/image URI dependencies without changing indices.

    Only URI values are replaced, using data URIs; original BIN bytes and all
    JSON semantics outside those URI fields are verified unchanged. This does
    not validate geometry, image decoding or extension-defined dependencies.
    """
    source, target = Path(source), Path(target)
    validate_authority(authority)
    if target.exists() or target.is_symlink():
        raise ValueError('GLB snapshot destination must be fresh')
    source_hash = file_hash(source)
    document, tail, binary = _glb_parts(source)
    original = copy.deepcopy(document)
    resources, replacements, total, embedded_total = [], {}, 0, 0
    buffers = document.get('buffers', [])
    for category in ('buffers', 'images'):
        values = document.get(category, [])
        if not isinstance(values, list) or len(values) > MAX_GLB_RESOURCES:
            raise ValueError('Invalid or excessive GLB resource declarations')
        for index, entry in enumerate(values):
            if not isinstance(entry, dict):
                raise TypeError('Invalid GLB resource entry')
            if category == 'buffers':
                declared_length = _integer(entry['byteLength'], 1)
            elif 'uri' in entry and 'bufferView' in entry:
                raise ValueError('GLB image cannot specify both URI and bufferView')
            uri = entry.get('uri')
            if uri is None:
                if 'uri' in entry:
                    raise ValueError('Null GLB URI is invalid')
                if category == 'buffers':
                    if index != 0 or binary is None or not 0 <= len(binary) - declared_length <= 3:
                        raise ValueError('Invalid GLB-stored buffer length or index')
                elif 'bufferView' not in entry:
                    raise ValueError('GLB image has no resource source')
                continue
            if not isinstance(uri, str):
                raise TypeError('GLB URI must be a string')
            if uri.startswith('data:'):
                content, mime = _data_uri(uri, category)
                embedded_total += len(content)
                if embedded_total > MAX_TOTAL_BYTES:
                    raise ValueError('GLB inline data limit exceeded')
            else:
                path = _glb_external_path(uri, authority)
                content, provenance = _external_bytes(SimpleNamespace(filepath=str(path)), authority)
                total += len(content)
                if total > MAX_TOTAL_BYTES or len(resources) >= MAX_GLB_RESOURCES:
                    raise ValueError('GLB external resource limit exceeded')
                mime = 'application/octet-stream' if category == 'buffers' else _image_mime(content)
                frozen = target.parent / (provenance['sha256'] + '.glb-resource')
                if frozen.exists():
                    if frozen.is_symlink() or file_hash(frozen) != provenance['sha256']:
                        raise ValueError('Frozen GLB dependency changed')
                else:
                    with frozen.open('xb') as stream:
                        stream.write(content)
                if file_hash(frozen) != provenance['sha256']:
                    raise ValueError('Frozen GLB dependency byte mismatch')
                resources.append({**provenance, 'category': category, 'index': index, 'uri': uri,
                                  'mime_type': mime, 'bytes': len(content), 'frozen_path': str(frozen)})
                replacements[(category, index)] = provenance['sha256']
                entry['uri'] = 'data:' + mime + ';base64,' + base64.b64encode(content).decode('ascii')
            if category == 'buffers' and len(content) < declared_length:
                raise ValueError('GLB buffer resource is shorter than declared byteLength')
            if category == 'images' and entry.get('mimeType', mime) != mime:
                raise ValueError('GLB image mimeType differs from encoded content')
    if binary is not None and (not buffers or 'uri' in buffers[0]):
        raise ValueError('GLB BIN chunk has no corresponding first buffer')
    if resources:
        encoded = json.dumps(document, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        encoded += b' ' * (-len(encoded) % 4)
        size = 20 + len(encoded) + len(tail)
        if len(encoded) > MAX_GLB_JSON_BYTES or size > MAX_GLB_BYTES:
            raise ValueError('Derived GLB exceeds byte limits')
        with target.open('xb') as stream:
            stream.write(struct.pack('<4sII', b'glTF', 2, size))
            stream.write(struct.pack('<II', len(encoded), 0x4E4F534A))
            stream.write(encoded)
            stream.write(tail)
    else:
        with source.open('rb') as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst)
    observed, observed_tail, _ = _glb_parts(target)
    if observed_tail != tail:
        raise ValueError('GLB binary chunk changed during dependency freezing')
    for (category, index), expected_hash in replacements.items():
        content, _ = _data_uri(observed[category][index]['uri'], category)
        if digest(content) != expected_hash:
            raise ValueError('Embedded GLB dependency differs from frozen bytes')
        observed[category][index]['uri'] = original[category][index]['uri']
    if observed != original:
        raise ValueError('GLB JSON semantics changed outside frozen URI fields')
    if file_hash(source) != source_hash or any(file_hash(item['read_path']) != item['sha256'] for item in resources):
        raise ValueError('GLB input or external dependency changed during freezing')
    return {'protocol': 'l1-glb-resource-snapshot-v1', 'source': str(source), 'source_sha256': source_hash,
            'output': str(target), 'output_sha256': file_hash(target), 'resources': resources,
            'changed_glb': bool(resources), 'total_external_bytes': total,
            'authority_sha256': digest(json.dumps(authority, sort_keys=True, allow_nan=False).encode()),
            'verification': {'binary_chunk_unchanged': True, 'json_except_uri_unchanged': True,
                             'embedded_resource_hashes_match': True},
            'scope': 'standard_buffer_and_image_uri_dependencies',
            'not_assessed': ['geometry_or_material_validity', 'image_decoding', 'extension_defined_dependencies',
                             'complete_filesystem_or_network_isolation']}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def _regular(path, root):
    root, path = Path(root), Path(path)
    if not root.is_absolute() or root == Path('/') or root.is_symlink() or not root.is_dir():
        raise ValueError('Resource authority root is absent, symbolic or overly broad')
    if not path.is_absolute() or not path.is_relative_to(root):
        raise ValueError('Resource file is outside authorized root')
    current = root
    for part in path.relative_to(root).parts:
        if part in {'', '.', '..'}:
            raise ValueError('Unsafe resource path component')
        current = current / part
        if current.is_symlink():
            raise ValueError('Resource path has a symlink component')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Resource file missing or escapes authorized root')
    return path


def validate_authority(authority):
    if (not isinstance(authority, dict) or authority.get('protocol') != AUTHORITY_PROTOCOL
            or authority.get('mode') not in {'declared_files', 'generated_workspace'}):
        raise ValueError('Invalid resource authority protocol/mode')
    root = Path(authority['storage_root'])
    if not root.is_absolute() or root == Path('/') or root.is_symlink() or not root.is_dir():
        raise ValueError('Invalid resource storage root')
    origin = Path(authority['origin_scene'])
    if not origin.is_absolute() or origin.suffix.lower() != '.blend':
        raise ValueError('Resource origin must identify the original native scene path')
    if any(part == '..' for part in origin.parts):
        raise ValueError('Unnormalized resource origin')
    if authority['mode'] == 'generated_workspace':
        if origin.parent != root or authority.get('files') not in (None, {}):
            raise ValueError('Generated scene must be rooted in its exact execution workspace')
    else:
        files = authority['files']
        if not isinstance(files, dict) or len(files) > 128:
            raise ValueError('Invalid declared resource file map')
        for authored, entry in files.items():
            key = Path(authored)
            if (not key.is_absolute() or not key.is_relative_to(origin.parent) or '..' in key.parts
                    or not isinstance(entry, dict) or not isinstance(entry.get('sha256'), str)
                    or len(entry['sha256']) != 64 or any(c not in '0123456789abcdef' for c in entry['sha256'])):
                raise ValueError('Invalid authored file path or expected hash')
            _regular(Path(entry['path']), root)
    return authority


def _external_bytes(image, authority):
    authored = image.filepath
    if not isinstance(authored, str) or not authored or '\\' in authored or '\x00' in authored:
        raise ValueError('Invalid external image filepath')
    origin = Path(authority['origin_scene'])
    # Lexical resolution avoids reopening or trusting the original mutable
    # submission. The declared map points instead at its frozen source copy.
    candidate = origin.parent / authored[2:] if authored.startswith('//') else Path(authored)
    if not candidate.is_absolute():
        candidate = origin.parent / candidate
    candidate = Path(os.path.abspath(candidate))
    if authority['mode'] == 'declared_files':
        entry = authority['files'].get(str(candidate))
        if entry is None:
            raise ValueError('External image was not included in the declared frozen submission')
        source, expected = Path(entry['path']), entry['sha256']
    else:
        source, expected = candidate, None
    _regular(source, Path(authority['storage_root']))
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('External image exceeds encoded byte limit')
    with source.open('rb') as stream:
        content = stream.read(MAX_FILE_BYTES + 1)
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError('External image empty or exceeds encoded byte limit')
    measured = digest(content)
    if expected is not None and measured != expected:
        raise ValueError('Declared image changed after source freezing')
    return content, {'kind': 'authorized_external', 'authored_path': authored,
                     'resolved_authored_path': str(candidate), 'read_path': str(source),
                     'expected_sha256': expected, 'sha256': measured}


def _reachable_images(roots):
    images, pending, seen = {}, list(roots), set()
    while pending:
        node = pending.pop()
        key = node.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > MAX_NODES:
            raise ValueError('Resource reachable node limit exceeded')
        if node.type in {'TEX_IMAGE', 'TEX_ENVIRONMENT'}:
            image = node.image
            if image is None:
                raise ValueError('Reachable image/environment node has no image')
            images[image.as_pointer()] = image
        if node.type == 'GROUP':
            tree = node.node_tree
            if tree is None or tree.library is not None:
                raise ValueError('Missing or linked shader group dependency is unsupported')
            pending.extend(value for value in tree.nodes if value.type == 'GROUP_OUTPUT' and value.is_active_output)
        pending.extend(link.from_node for socket in node.inputs if socket.enabled for link in socket.links)
    return list(images.values())


def _scene_images():
    import bpy
    roots = []
    def add_material(material):
        if material and material.use_nodes and material.node_tree:
            roots.extend(node for node in material.node_tree.nodes if node.type == 'OUTPUT_MATERIAL'
                         and node.is_active_output and node.target in {'ALL', 'CYCLES'})
    edits, hidden, objects = [], [], {}
    def set_temporarily(owner, key, value):
        edits.append((owner, key, getattr(owner, key)))
        setattr(owner, key, value)
    def prepare(layer):
        if layer.exclude or layer.collection.hide_render:
            return
        set_temporarily(layer, 'hide_viewport', False)
        set_temporarily(layer.collection, 'hide_viewport', False)
        for obj in layer.collection.objects:
            if not obj.hide_render:
                objects[obj.as_pointer()] = obj
        for child in layer.children:
            prepare(child)
    try:
        # Match the inspector's render-evaluated mesh scope, but restore every
        # temporary setting before saving the derivative scene.
        prepare(bpy.context.view_layer.layer_collection)
        for obj in objects.values():
            hidden.append((obj, obj.hide_get()))
            obj.hide_set(False)
            set_temporarily(obj, 'hide_viewport', False)
            for modifier in obj.modifiers:
                set_temporarily(modifier, 'show_viewport', modifier.show_render)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj in objects.values():
            if obj.library is not None or (obj.data is not None and obj.data.library is not None):
                raise ValueError('Linked render object/data dependencies require a library adapter')
            if obj.type == 'MESH':
                evaluated = obj.evaluated_get(depsgraph)
                mesh = evaluated.to_mesh()
                try:
                    for index in {face.material_index for face in mesh.polygons}:
                        material = (evaluated.material_slots[index].material
                                    if index < len(evaluated.material_slots) and evaluated.material_slots[index].link == 'OBJECT'
                                    else mesh.materials[index] if index < len(mesh.materials) else None)
                        add_material(material.original if material is not None else None)
                finally:
                    evaluated.to_mesh_clear()
            elif obj.type == 'LIGHT' and obj.data.use_nodes and obj.data.node_tree:
                roots.extend(node for node in obj.data.node_tree.nodes if node.type == 'OUTPUT_LIGHT' and node.is_active_output)
            elif obj.type not in {'EMPTY', 'CAMERA', 'LIGHT', 'ARMATURE', 'LATTICE', 'SPEAKER', 'LIGHT_PROBE'}:
                raise ValueError('Non-mesh render geometry resource discovery requires an adapter')
        world = bpy.context.scene.world
        if world and world.use_nodes and world.node_tree:
            roots.extend(node for node in world.node_tree.nodes if node.type == 'OUTPUT_WORLD' and node.is_active_output)
        return _reachable_images(roots)
    finally:
        for owner, key, value in reversed(edits):
            setattr(owner, key, value)
        for obj, value in hidden:
            obj.hide_set(value)


def snapshot_embedded_glb(source, target):
    source, target = Path(source), Path(target)
    if source.is_symlink() or not source.is_file() or source.suffix.lower() != '.glb':
        raise ValueError('Invalid GLB source')
    size = source.stat().st_size
    if not 20 <= size <= 512 * 1024 * 1024:
        raise ValueError('GLB size outside snapshot limits')
    source_hash = file_hash(source)
    with source.open('rb') as stream:
        magic, version, length = struct.unpack('<4sII', stream.read(12))
        if magic != b'glTF' or version != 2 or length != size:
            raise ValueError('Invalid GLB header/length')
        chunk_length, chunk_type = struct.unpack('<II', stream.read(8))
        if chunk_type != 0x4E4F534A or chunk_length % 4 or not 0 < chunk_length <= min(4 * 1024 * 1024, size - 20):
            raise ValueError('Invalid or oversized GLB JSON chunk')
        document = json.loads(stream.read(chunk_length))
        if not isinstance(document, dict) or document.get('asset', {}).get('version') != '2.0':
            raise ValueError('Invalid GLB asset metadata')
        for category in ('buffers', 'images'):
            values = document.get(category, [])
            if not isinstance(values, list):
                raise TypeError('Invalid GLB resource declarations')
            for value in values:
                if not isinstance(value, dict):
                    raise TypeError('Invalid GLB resource entry')
                uri = value.get('uri')
                if uri is not None and (not isinstance(uri, str) or not uri.startswith('data:')):
                    raise ValueError('External GLB URI dependencies require a freeze/remap adapter')
        binary_chunks = 0
        while stream.tell() < size:
            header = stream.read(8)
            if len(header) != 8:
                raise ValueError('Truncated GLB chunk header')
            chunk_length, chunk_type = struct.unpack('<II', header)
            if chunk_type != 0x004E4942 or chunk_length % 4 or stream.tell() + chunk_length > size:
                raise ValueError('Unknown or invalid GLB binary chunk')
            binary_chunks += 1
            stream.seek(chunk_length, 1)
        if binary_chunks > 1:
            raise ValueError('Multiple GLB binary chunks unsupported')
    shutil.copyfile(source, target)
    if file_hash(source) != source_hash or file_hash(target) != source_hash:
        raise ValueError('GLB changed during freezing')
    return {'protocol': 'l1-embedded-glb-snapshot-v1', 'source': str(source), 'source_sha256': source_hash,
            'output': str(target), 'output_sha256': source_hash,
            'scope': 'no_external_standard_buffer_or_image_uri',
            'not_assessed': ['geometry_or_material_validity', 'nonstandard_extension_resource_semantics']}


def snapshot_native_images(source, output, *, authority, frames=(1,), glb_source=None):
    """Run only inside trusted Blender with autoexec disabled by its launcher."""
    import bpy
    source, output = Path(source), Path(output)
    record = {'protocol': PROTOCOL, 'status': 'not_measurable', 'source': str(source), 'images': [],
              'frames': list(frames), 'scope': 'render_reachable_native_images_at_declared_frames',
              'not_assessed': ['linked_libraries', 'geometry_caches', 'extension_defined_GLB_dependencies',
                               'undeclared_frames', 'complete_filesystem_or_network_isolation']}
    try:
        validate_authority(authority)
        if (not source.is_file() or source.is_symlink() or source.suffix.lower() != '.blend'
                or not frames or len(frames) > 16 or any(type(value) is not int or value < 0 for value in frames)
                or output.exists()):
            raise ValueError('Invalid snapshot input, frame scope or nonempty output target')
        output.mkdir(parents=True)
        record['source_sha256'] = file_hash(source)
        record['authority_sha256'] = digest(json.dumps(authority, sort_keys=True, allow_nan=False).encode())
        if glb_source is not None:
            record['glb'] = snapshot_glb_resources(glb_source, output / 'scene.glb', authority=authority)
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
        frame, subframe = bpy.context.scene.frame_current, bpy.context.scene.frame_subframe
        images = {}
        for value in frames:
            bpy.context.scene.frame_set(value)
            for image in _scene_images():
                images[image.as_pointer()] = image
        bpy.context.scene.frame_set(frame, subframe=subframe)
        if len(images) > MAX_IMAGES:
            raise ValueError('Resource image count limit exceeded')
        total, changed = 0, False
        for image in images.values():
            if image.library is not None or image.source not in {'FILE', 'GENERATED'} or len(image.packed_files) > 1:
                raise ValueError('Linked, tiled, sequence, movie or multiview images require an adapter')
            metadata = {'name': image.name, 'filepath': image.filepath, 'source': image.source,
                        'colorspace': image.colorspace_settings.name, 'alpha_mode': image.alpha_mode}
            if image.packed_file is not None:
                if image.packed_file.size > MAX_FILE_BYTES:
                    raise ValueError('Packed image exceeds encoded byte limit')
                content = bytes(image.packed_file.data)
                provenance = {'kind': 'packed', 'sha256': digest(content)}
            elif image.source == 'FILE':
                content, provenance = _external_bytes(image, authority)
            else:
                raise ValueError('Unpacked generated image persistence requires an adapter')
            total += len(content)
            if total > MAX_TOTAL_BYTES:
                raise ValueError('Total resource byte limit exceeded')
            filename = output / (provenance['sha256'] + '.image-bytes')
            if not filename.exists():
                filename.write_bytes(content)
            if file_hash(filename) != provenance['sha256']:
                raise ValueError('Frozen resource bytes changed')
            entry = {**metadata, **provenance, 'bytes': len(content), 'frozen_path': str(filename)}
            record['images'].append(entry)
            if provenance['kind'] == 'authorized_external':
                image.pack(data=content, data_len=len(content))
                if image.packed_file is None or digest(bytes(image.packed_file.data)) != provenance['sha256']:
                    raise ValueError('Packed scene bytes differ from the authorized frozen input')
                changed = True
        target = output / 'scene.blend'
        if changed:
            bpy.ops.wm.save_as_mainfile(filepath=str(target), relative_remap=False, check_existing=False)
        else:
            shutil.copyfile(source, target)
        # Check the serialized artifact, not only the in-memory image.pack()
        # result. The reopened derived scene must retain frame/metadata and
        # the same render-reachable image set across all declared frames.
        bpy.ops.wm.open_mainfile(filepath=str(target), load_ui=False, use_scripts=False)
        if bpy.context.scene.frame_current != frame or bpy.context.scene.frame_subframe != subframe:
            raise ValueError('Derived scene changed the saved frame state')
        observed = {}
        for value in frames:
            bpy.context.scene.frame_set(value)
            for image in _scene_images():
                observed[image.name] = image
        bpy.context.scene.frame_set(frame, subframe=subframe)
        if set(observed) != {item['name'] for item in record['images']}:
            raise ValueError('Derived scene changed its render-reachable image set')
        for item in record['images']:
            image = observed[item['name']]
            if (image.packed_file is None or digest(bytes(image.packed_file.data)) != item['sha256']
                    or image.colorspace_settings.name != item['colorspace'] or image.alpha_mode != item['alpha_mode']
                    or image.filepath != item['filepath']):
                raise ValueError('Derived scene did not preserve packed bytes or image metadata')
        record['reopen_verification'] = {'passed': True, 'images': len(observed), 'frames': list(frames),
                                         'saved_frame': frame, 'saved_subframe': subframe}
        if file_hash(source) != record['source_sha256']:
            raise ValueError('Original scene changed while freezing dependencies')
        for item in record['images']:
            if item['kind'] == 'authorized_external' and file_hash(item['read_path']) != item['sha256']:
                raise ValueError('External dependency changed while freezing scene')
        record.update(status='ready', output_scene=str(target), output_sha256=file_hash(target),
                      total_image_bytes=total, changed_scene=changed,
                      authority=authority, original_frame=frame, original_subframe=subframe)
    except (AttributeError, IndexError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        record.update(reason=str(error), error_type=type(error).__name__)
    return record
