"""Trusted Cycles EMIT oracle for generated cube texture fixtures only.

This is a calibration/test oracle, NOT a production evaluator or task score.
Its fixed world-projection UV atlas is independent of candidate texture UVs.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--alpha-used', action='store_true')
parser.add_argument('--color-space')
parser.add_argument('--alpha-mode')
parser.add_argument('--variants', nargs='+')
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
args.output.mkdir(parents=True, exist_ok=True)
rows = []
reference = None
manifest = json.loads((args.assets / 'fixture-manifest.json').read_text())
cases = [(entry['variant'], 'scene.blend', entry['expected']) for entry in manifest]
cases += [(variant, 'scene.glb', 'ok') for variant in ('base', 'external', 'compensated_flip')]
if args.variants:
    cases = [entry for entry in cases if entry[0] in args.variants and entry[1].endswith('.blend')]
for variant, filename, expected in cases:
    source = args.assets / variant / filename
    label = variant + ('-glb' if filename.endswith('.glb') else '')
    row = {'variant': label, 'expected': expected, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    rows.append(row)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if filename.endswith('.blend'):
        bpy.ops.wm.open_mainfile(filepath=str(source.resolve()))
    else:
        bpy.ops.import_scene.gltf(filepath=str(source.resolve()))
    # Fixture-only dependency guard: do not bake a fallback color for absence.
    missing = [image.filepath for image in bpy.data.images if image.source == 'FILE' and not image.packed_file
               and not Path(bpy.path.abspath(image.filepath)).is_file()]
    if missing:
        row.update(status='not_measurable', missing=missing)
        continue
    objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    assert len(objects) == 1
    obj = objects[0]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mesh = obj.data
    for image in bpy.data.images:
        if args.color_space:
            image.colorspace_settings.name = args.color_space
        if args.alpha_mode:
            image.alpha_mode = args.alpha_mode
    atlas = mesh.uv_layers.new(name='TRUSTED_WORLD_ATLAS')
    for face in mesh.polygons:
        normal = np.array(face.normal)
        axis = int(np.argmax(np.abs(normal)))
        axes = [value for value in range(3) if value != axis]
        tile = axis * 2 + int(normal[axis] > 0)
        for loop in face.loop_indices:
            point = np.array(obj.matrix_world @ mesh.vertices[mesh.loops[loop].vertex_index].co)
            u, v = point[axes] / .01 + .5
            atlas.data[loop].uv = ((tile % 3 + u) / 3, (tile // 3 + v) / 2)
    mesh.uv_layers.active = atlas
    target = bpy.data.images.new('trusted-emission-target', width=96, height=64, float_buffer=True)
    for slot in obj.material_slots:
        tree = slot.material.node_tree
        shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
        output = next(node for node in tree.nodes if node.type == 'OUTPUT_MATERIAL' and node.is_active_output)
        assert len(shader.inputs['Base Color'].links) == 1
        color = shader.inputs['Base Color'].links[0].from_socket
        # Imported glTF defaults to active-render UV; freeze its original UV
        # explicitly before selecting the trusted atlas for bake output.
        for texture in [node for node in tree.nodes if node.type == 'TEX_IMAGE']:
            if not texture.inputs['Vector'].is_linked:
                uv_node = tree.nodes.new('ShaderNodeUVMap')
                uv_node.uv_map = mesh.uv_layers[0].name
                tree.links.new(uv_node.outputs['UV'], texture.inputs['Vector'])
        emission = tree.nodes.new('ShaderNodeEmission')
        tree.links.new(color, emission.inputs['Color'])
        if args.alpha_used:
            # Alpha/Alpha is exactly one on these nonzero-alpha fixtures, but
            # keeps the Alpha output live while observing the Color output.
            divide = tree.nodes.new('ShaderNodeMath')
            divide.operation = 'DIVIDE'
            tree.links.new(color.node.outputs['Alpha'], divide.inputs[0])
            tree.links.new(color.node.outputs['Alpha'], divide.inputs[1])
            tree.links.new(divide.outputs[0], emission.inputs['Strength'])
        tree.links.new(emission.outputs[0], output.inputs['Surface'])
        bake_node = tree.nodes.new('ShaderNodeTexImage')
        bake_node.image = target
        tree.nodes.active = bake_node
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 1
    scene.render.bake.margin = 0
    bpy.ops.object.bake(type='EMIT')
    pixels = np.array(target.pixels[:], dtype=np.float32).reshape(64, 96, 4)
    assert np.isfinite(pixels).all() and np.allclose(pixels[..., 3], 1)
    if reference is None:
        reference = pixels
    maximum = float(np.max(np.abs(pixels[..., :3] - reference[..., :3])))
    # A second independent bake records the actual UV field at these same
    # world surface samples. It will calibrate the numerical texture sampler.
    texture = color.node
    assert texture.type == 'TEX_IMAGE' and texture.inputs['Vector'].is_linked
    source_image = texture.image
    texture_pixels = np.array(source_image.pixels[:], dtype=np.float32).reshape(
        source_image.size[1], source_image.size[0], 4)
    coordinate = texture.inputs['Vector'].links[0].from_socket
    tree.links.new(coordinate, emission.inputs['Color'])
    bpy.ops.object.bake(type='EMIT')
    coordinates = np.array(target.pixels[:], dtype=np.float32).reshape(64, 96, 4)[..., :2]
    tree.links.new(texture.outputs['Alpha'], emission.inputs['Color'])
    bpy.ops.object.bake(type='EMIT')
    alpha_values = np.array(target.pixels[:], dtype=np.float32).reshape(64, 96, 4)[..., 0]
    path = args.output / f'{label}.npz'
    np.savez_compressed(path, linear_rgba=pixels, texture_rgba=texture_pixels, uv_rg=coordinates, alpha_scalar=alpha_values)
    row.update(status='ok' if maximum <= 1e-5 else 'failed', max_abs_linear_rgb_error=maximum,
               payload=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
               method='trusted_world_uv_atlas_cycles_emit', tolerance=1e-5,
               texture_space=source_image.colorspace_settings.name, image_is_float=source_image.is_float,
               alpha_mode=source_image.alpha_mode, alpha_used=args.alpha_used,
               interpolation=texture.interpolation, extension=texture.extension)
    print(label, row['status'], maximum, flush=True)
(args.output / 'oracle.json').write_text(json.dumps(rows, indent=2) + '\n')
assert all(row['status'] == row['expected'] for row in rows), rows
