"""Cube with external core GLB dependencies; workflow fixture, not task quality."""

import json
import struct
from pathlib import Path

import bpy

mode = json.loads(Path('mode.json').read_text())['mode']
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=.01)
obj = bpy.context.object
if mode in {'mixed', 'mixed_parameter_drift'}:
    image = bpy.data.images.new('packed native image', width=4, height=4, alpha=True)
    image.pixels[:] = [.3, .6, .9, 1.] * 16
    image.filepath_raw = str(Path.cwd() / 'albedo.png')
    image.file_format = 'PNG'
    image.save()
    image = bpy.data.images.load(str(Path.cwd() / 'albedo.png'), check_existing=False)
    image.pack()
    material = bpy.data.materials.new('textured fixture')
    material.use_nodes = True
    texture = material.node_tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    material.node_tree.links.new(texture.outputs['Color'], material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    if mode == 'mixed_parameter_drift' and Path.cwd().name == '2':
        material.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .9
    obj.data.materials.append(material)
bpy.context.scene.frame_set(1)
bpy.ops.export_scene.gltf(filepath=str(Path.cwd() / 'scene.glb'), export_format='GLB')
bpy.ops.wm.save_as_mainfile(filepath=str(Path.cwd() / 'scene.blend'))

glb = Path('scene.glb')
raw = glb.read_bytes()
length, kind = struct.unpack('<II', raw[12:20])
assert kind == 0x4E4F534A
document = json.loads(raw[20:20 + length])
binary_length, kind = struct.unpack('<II', raw[20 + length:28 + length])
assert kind == 0x004E4942
binary = raw[28 + length:]
assert len(binary) == binary_length
if mode in {'mixed', 'mixed_parameter_drift'}:
    image = document['images'][0]
    view = document['bufferViews'][image.pop('bufferView')]
    offset = view.get('byteOffset', 0)
    Path('export.png').write_bytes(binary[offset:offset + view['byteLength']])
    image['uri'] = 'export.png'
Path('geometry.bin').write_bytes(binary)
document['buffers'][0]['uri'] = 'geometry.bin'
encoded = json.dumps(document).encode()
encoded += b' ' * (-len(encoded) % 4)
glb.write_bytes(struct.pack('<4sII', b'glTF', 2, 20 + len(encoded))
                + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded)
if ((mode == 'missing_baseline' and Path.cwd().name == 'workspace')
        or (mode == 'missing_seed' and Path.cwd().name == '0')):
    Path('geometry.bin').unlink()  # Remove only this fixture's generated dependency.
