"""Real, unchanged Principled render pairs plus independent diffuse-color bake."""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import bpy
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--repo', type=Path, required=True)
parser.add_argument('--adapter', type=Path, required=True)
parser.add_argument('--assets', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
sys.path.insert(0, str(args.repo))


def load_module(name, path):
    module_spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


describe_material_fields = load_module('raw_shader_fields', args.repo / 'src/evaluator/l1_shader_fields.py').describe_material_fields
TextureCapture = load_module('texture_capture', args.repo / 'src/evaluator/l1_texture_capture.py').TextureCapture

spec = importlib.util.spec_from_file_location('principled_adapter', args.adapter)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
source_paths = [args.adapter, Path(__file__), args.repo / 'src/evaluator/l1_shader_fields.py',
                args.repo / 'src/evaluator/l1_texture_capture.py', args.repo / 'src/evaluator/l1_texture_fields.py',
                args.adapter.with_name('l1_shader_fields.py')]
source_hashes = {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}

VARIANTS = ('base', 'coat_dead', 'coat_active', 'coat_value_zero', 'coat_math_zero', 'coat_math_divide_zero',
            'sheen_dead', 'anisotropic_dead', 'film_dead', 'film_below_kernel_cutoff',
            'subsurface_dead', 'subsurface_zero_scale', 'emission_dead_color', 'emission_dead_strength',
            'alpha_times_zero', 'alpha_divide_zero', 'alpha_zero_divide', 'alpha_times_one',
            'coat_below_cutoff', 'coat_at_cutoff', 'emission_at_cutoff', 'emission_cutoff_unlinked',
            'emission_cutoff_default_color', 'emission_folded_cutoff',
            'roughness_negative', 'roughness_zero', 'roughness_above_one', 'roughness_one',
            'metallic_negative', 'metallic_zero', 'metallic_above_one', 'metallic_one', 'aov_alpha')
manifest = []
for variant in VARIANTS:
    directory = args.output / variant
    directory.mkdir(parents=True)
    bpy.ops.wm.open_mainfile(filepath=str(args.assets / 'alpha_pixels/scene.blend'))
    original = next(obj for obj in bpy.context.scene.objects if obj.type == 'MESH')
    material = original.material_slots[0].material
    bpy.data.objects.remove(original, do_unlink=True)
    bpy.ops.mesh.primitive_plane_add(size=2)
    obj = bpy.context.object
    obj.data.materials.append(material)
    tree = material.node_tree
    shader = next(node for node in tree.nodes if node.type == 'BSDF_PRINCIPLED')
    texture = next(node for node in tree.nodes if node.type == 'TEX_IMAGE')

    def value_link(name, value, tree=tree, shader=shader):
        node = tree.nodes.new('ShaderNodeValue')
        node.outputs[0].default_value = value
        tree.links.new(node.outputs[0], shader.inputs[name])

    def alpha_link(name, tree=tree, texture=texture, shader=shader):
        tree.links.new(texture.outputs['Alpha'], shader.inputs[name])

    def alpha_math(name, operation, value, tree=tree, texture=texture, shader=shader):
        node = tree.nodes.new('ShaderNodeMath')
        node.operation = operation
        tree.links.new(texture.outputs['Alpha'], node.inputs[0])
        node.inputs[1].default_value = value
        tree.links.new(node.outputs[0], shader.inputs[name])

    if variant.startswith('coat_'):
        alpha_link('Coat Roughness')
        if variant == 'coat_active':
            shader.inputs['Coat Weight'].default_value = .7
        elif variant == 'coat_value_zero':
            value_link('Coat Weight', 0.)
        elif variant == 'coat_math_zero':
            alpha_math('Coat Weight', 'MULTIPLY', 0.)
        elif variant == 'coat_math_divide_zero':
            alpha_math('Coat Weight', 'DIVIDE', 0.)
        elif variant in {'coat_below_cutoff', 'coat_at_cutoff'}:
            shader.inputs['Coat Weight'].default_value = 5e-6 if variant == 'coat_below_cutoff' else 1e-5
    elif variant == 'sheen_dead':
        alpha_link('Sheen Roughness')
    elif variant == 'anisotropic_dead':
        alpha_link('Anisotropic Rotation')
    elif variant.startswith('film_'):
        alpha_link('Thin Film IOR')
        if variant == 'film_below_kernel_cutoff':
            shader.inputs['Thin Film Thickness'].default_value = .05
    elif variant == 'subsurface_dead':
        alpha_link('Subsurface Scale')
    elif variant == 'subsurface_zero_scale':
        shader.inputs['Subsurface Weight'].default_value = .5
        shader.inputs['Subsurface Scale'].default_value = 0.
        alpha_link('Subsurface Anisotropy')
    elif variant in {'emission_dead_color', 'emission_at_cutoff', 'emission_cutoff_default_color', 'emission_folded_cutoff'}:
        # Scalar->color conversion is deliberately on a dead branch. Parsing
        # it before pruning would incorrectly reject an otherwise valid graph.
        alpha_link('Emission Color')
        if variant in {'emission_at_cutoff', 'emission_cutoff_default_color'}:
            shader.inputs['Emission Strength'].default_value = 1e-5
        if variant == 'emission_cutoff_default_color':
            shader.inputs['Emission Color'].default_value = (.2, .4, .6, 1.)
        if variant == 'emission_folded_cutoff':
            value_link('Emission Strength', 1e-5)
    elif variant == 'emission_cutoff_unlinked':
        shader.inputs['Emission Strength'].default_value = 1e-5
    elif variant == 'emission_dead_strength':
        shader.inputs['Emission Color'].default_value = (0., 0., 0., 1.)
        alpha_link('Emission Strength')
    elif variant == 'alpha_zero_divide':
        node = tree.nodes.new('ShaderNodeMath')
        node.operation = 'DIVIDE'
        node.inputs[0].default_value = 0.
        tree.links.new(texture.outputs['Alpha'], node.inputs[1])
        tree.links.new(node.outputs[0], shader.inputs['Roughness'])
    elif variant.startswith('alpha_'):
        alpha_math('Roughness', 'DIVIDE' if variant == 'alpha_divide_zero' else 'MULTIPLY',
                   1. if variant == 'alpha_times_one' else 0.)
    elif variant.startswith(('roughness_', 'metallic_')):
        name = 'Roughness' if variant.startswith('roughness_') else 'Metallic'
        value = -.5 if variant.endswith('negative') else 1.5 if variant.endswith('above_one') else 0. if variant.endswith('zero') else 1.
        value_link(name, value)
    elif variant == 'aov_alpha':
        aov = bpy.context.view_layer.aovs.add()
        aov.name, aov.type = 'auxiliary_alpha', 'VALUE'
        output_aov = tree.nodes.new('ShaderNodeOutputAOV')
        output_aov.aov_name = aov.name
        tree.links.new(texture.outputs['Alpha'], output_aov.inputs['Value'])

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.seed = 0
    scene.cycles.use_denoising = False
    scene.cycles.use_adaptive_sampling = False
    scene.render.resolution_x = scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_depth = '32'
    scene.world = bpy.data.worlds.new('constant environment')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.2, .2, .2, 1.)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.
    bpy.ops.object.camera_add(location=(0, 0, 3))
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 2.
    scene.camera = camera
    bpy.ops.object.light_add(type='AREA', location=(.6, .6, 2))
    light = bpy.context.object
    light.data.energy = 50.
    light.data.shape = 'DISK'
    light.data.size = 1.
    default_uv = obj.data.uv_layers.active.name
    capture = TextureCapture(directory / 'pixels', resource_roots=[])
    options = {'capture': capture, 'default_uv': default_uv, 'uv_layers': list(obj.data.uv_layers.keys())}
    raw = describe_material_fields(material, **options)
    effective = adapter.describe_principled(material, **options)
    slots = adapter.capture_principled_fields([material, None], used_slots={0}, **options)
    assert slots['slots'] == [effective, {'status': 'unused'}]
    (directory / 'slots.json').write_text(json.dumps(slots, indent=2))
    (directory / 'raw-fields.json').write_text(json.dumps(raw, indent=2))
    (directory / 'effective-fields.json').write_text(json.dumps(effective, indent=2))
    bpy.ops.wm.save_as_mainfile(filepath=str(directory / 'scene.blend'), relative_remap=False)
    scene.render.filepath = str(directory / 'render.exr')
    bpy.ops.render.render(write_still=True)
    render = bpy.data.images.load(scene.render.filepath, check_existing=False)
    pixels = np.empty(32 * 32 * 4, dtype=np.float32)
    render.pixels.foreach_get(pixels)
    arrays = {'render': pixels.copy().reshape(32, 32, 4)}
    # Keep the actual Principled shader. This avoids the previous emission-only
    # oracle changing which Principled branches the compiler prunes.
    shader.inputs['Specular IOR Level'].default_value = 0.
    # One sample allows a separate geometry UV pass to locate the exact
    # sample. Averaging UV then evaluating a nonlinear texture is not valid.
    scene.cycles.samples = 1
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    target = bpy.data.images.new('trusted_color_bake', width=32, height=32, float_buffer=True)
    target.colorspace_settings.name = 'Linear Rec.709'
    bake = tree.nodes.new('ShaderNodeTexImage')
    bake.image = target
    tree.nodes.active = bake
    scene.render.bake.margin = 0
    bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'})
    target.pixels.foreach_get(pixels)
    arrays['diffuse_color'] = pixels.copy().reshape(32, 32, 4)
    bpy.ops.object.bake(type='UV')
    target.pixels.foreach_get(pixels)
    arrays['uv'] = pixels.copy().reshape(32, 32, 4)
    # Re-read the saved EXR independently after all bakes. A shared numpy view
    # must not let foreach_get overwrite the evidence for the original BSDF.
    render.pixels.foreach_get(pixels)
    assert np.array_equal(arrays['render'].reshape(-1), pixels)
    assert not np.array_equal(arrays['render'], arrays['uv'])
    np.savez_compressed(directory / 'oracle.npz', **arrays)
    manifest.append({'variant': variant, 'raw_status': raw['status'], 'effective_status': effective['status'],
                     'scene': str(directory / 'scene.blend'), 'oracle': str(directory / 'oracle.npz'),
                     'renderer': {'version': list(bpy.app.version), 'build_hash': bpy.app.build_hash.decode()},
                     'artifact_sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                         for name in ('scene.blend', 'render.exr', 'oracle.npz', 'effective-fields.json', 'slots.json')},
                     'render_pixels_sha256': hashlib.sha256(pixels.tobytes()).hexdigest(),
                     'render_equals_saved_exr': True, 'render_samples': 16, 'bake_samples': 1,
                     'aovs': [{'name': item.name, 'type': item.type} for item in scene.view_layers[0].aovs],
                     'source_sha256': source_hashes,
                     'uv_oracle': 'geometry_UV_bake'})
assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in source_hashes.items())
(args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
