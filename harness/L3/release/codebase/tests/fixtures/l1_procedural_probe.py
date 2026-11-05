"""Real Blender cases for the reachable no-bitmap audit, not task solutions."""
import importlib.util
import json
import sys
from pathlib import Path

import bpy

project = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("inspector", project / "src/evaluator/l1_blender.py")
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)
results = {}


def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.object
    mat = bpy.data.materials.new("Surface")
    mat.use_nodes = True
    obj.data.materials.append(mat)
    return obj, mat, mat.node_tree, mat.node_tree.nodes.get("Principled BSDF")


def bitmap(tree):
    node = tree.nodes.new("ShaderNodeTexImage")
    node.image = bpy.data.images.new("Generated_not_external", width=8, height=8)
    return node


def capture(name):
    facts, _ = inspector._collect()
    results[name] = facts["procedural_materials"]


obj, mat, tree, shader = setup()
capture("constant")
editor = bpy.context.scene.sequence_editor_create()
bpy.context.scene.render.use_sequencer = True
capture('empty_sequencer')
editor.strips.new_effect(name='Uninspected output', type='COLOR', channel=1, frame_start=1, length=100)
capture('sequencer_output')
bpy.context.scene.render.use_sequencer = False
capture('disabled_sequencer')
noise = tree.nodes.new("ShaderNodeTexNoise")
tree.links.new(noise.outputs["Color"], shader.inputs["Base Color"])
capture("noise")
image = bitmap(tree)
capture("unused_image_node")
tree.links.new(image.outputs["Color"], shader.inputs["Base Color"])
capture("generated_image")
image.image.pack()
capture("packed_image")
tree.links.new(image.outputs["Color"], shader.inputs["Roughness"])
tree.links.new(noise.outputs["Color"], shader.inputs["Base Color"])
capture("image_roughness")

obj, mat, tree, shader = setup()
group = bpy.data.node_groups.new("Nested", "ShaderNodeTree")
group.interface.new_socket(name="Color", in_out="OUTPUT", socket_type="NodeSocketColor")
group_out = group.nodes.new("NodeGroupOutput")
texture = bitmap(group)
group.links.new(texture.outputs["Color"], group_out.inputs["Color"])
instance = tree.nodes.new("ShaderNodeGroup")
instance.node_tree = group
tree.links.new(instance.outputs["Color"], shader.inputs["Base Color"])
capture("nested_image")
tree.links.remove(shader.inputs["Base Color"].links[0])
capture("unused_group")

group.interface.new_socket(name="Incoming", in_out="INPUT", socket_type="NodeSocketColor")
group_in = group.nodes.new("NodeGroupInput")
group.links.new(group_in.outputs["Incoming"], group_out.inputs["Color"])
image = bitmap(tree)
tree.links.new(image.outputs["Color"], instance.inputs["Incoming"])
tree.links.new(instance.outputs["Color"], shader.inputs["Base Color"])
capture("image_through_group_input")

obj, mat, tree, shader = setup()
unused = bpy.data.materials.new("UnusedBitmap")
unused.use_nodes = True
image = bitmap(unused.node_tree)
unused.node_tree.links.new(image.outputs["Color"], unused.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
obj.data.materials.append(unused)
capture("unused_material_slot")
obj.material_slots[0].link = "OBJECT"
obj.material_slots[0].material = unused
capture("object_material_override")
bpy.context.view_layer.material_override = mat
capture("layer_material_override")

obj, mat, tree, shader = setup()
obj.data.materials.clear()
capture("unassigned")

obj, mat, tree, shader = setup()
world = bpy.data.worlds.new("World")
world.use_nodes = True
bpy.context.scene.world = world
hdri = world.node_tree.nodes.new("ShaderNodeTexEnvironment")
hdri.image = bpy.data.images.new("HDRI", width=8, height=8)
world.node_tree.links.new(hdri.outputs["Color"], world.node_tree.nodes.get("Background").inputs["Color"])
capture("world_hdri")

obj, mat, tree, shader = setup()
light = bpy.data.lights.new("Area", "AREA")
light.use_nodes = True
lamp = bpy.data.objects.new("Lamp", light)
bpy.context.collection.objects.link(lamp)
image = bitmap(light.node_tree)
emission = light.node_tree.nodes.get("Emission")
light.node_tree.links.new(image.outputs["Color"], emission.inputs["Color"])
capture("light_image")

obj, mat, tree, shader = setup()
compositor = bpy.data.node_groups.new("Compositor", "CompositorNodeTree")
compositor.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
out = compositor.nodes.new("NodeGroupOutput")
image = compositor.nodes.new("CompositorNodeImage")
image.image = bpy.data.images.new("FakeMain", width=8, height=8)
compositor.links.new(image.outputs["Image"], out.inputs["Image"])
bpy.context.scene.compositing_node_group = compositor
capture("compositor_image")

obj, mat, tree, shader = setup()
mod = obj.modifiers.new("Shape", "DISPLACE")
mod.texture = bpy.data.textures.new("Height", type="IMAGE")
mod.texture.image = bpy.data.images.new("HeightMap", width=8, height=8)
capture("image_displacement")

obj, mat, tree, shader = setup()
geometry = bpy.data.node_groups.new("Geometry", "GeometryNodeTree")
geometry.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
geometry.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
image_socket = geometry.interface.new_socket(name="Image", in_out="INPUT", socket_type="NodeSocketImage")
gin = geometry.nodes.new("NodeGroupInput")
gout = geometry.nodes.new("NodeGroupOutput")
geometry.links.new(gin.outputs['Geometry'], gout.inputs['Geometry'])
modifier = obj.modifiers.new("Image geometry", "NODES")
modifier.node_group = geometry
getattr(modifier.properties.inputs, image_socket.identifier).value = bpy.data.images.new("Geometry input", width=8, height=8)
capture("unused_geometry_image_input")
texture = geometry.nodes.new("GeometryNodeImageTexture")
position = geometry.nodes.new("GeometryNodeSetPosition")
geometry.links.new(gin.outputs['Image'], texture.inputs['Image'])
geometry.links.new(gin.outputs['Geometry'], position.inputs['Geometry'])
geometry.links.new(texture.outputs['Color'], position.inputs['Offset'])
geometry.links.new(position.outputs['Geometry'], gout.inputs['Geometry'])
capture("geometry_image_input")

obj, mat, tree, shader = setup()
image = bitmap(tree)
mix = tree.nodes.new('ShaderNodeMixRGB')
mix.mute = True
color = tree.nodes.new('ShaderNodeRGB')
color.outputs[0].default_value = (0.2, 0.3, 0.4, 1)
tree.links.new(color.outputs[0], mix.inputs[1])
tree.links.new(image.outputs['Color'], mix.inputs[2])
tree.links.new(mix.outputs['Color'], shader.inputs['Base Color'])
capture("muted_mix_unused_image")
tree.links.new(image.outputs['Color'], mix.inputs[1])
capture("muted_mix_used_image")

obj, mat, tree, shader = setup()
bpy.context.scene.view_layers.new('Uninspected layer')
capture("other_view_layer")

obj, mat, tree, shader = setup()
tree.nodes.new("ShaderNodeScript")
# Unconnected scripts are ignored; connected OSL requires socket compilation,
# which is deliberately not executed by the no-bitmap inspector.
capture("unused_script")
audit = inspector._procedural_materials().MaterialAudit(max_nodes=0)
audit.materials([mat], {0}, "limit")
results["limit"] = audit.result(frame=1)

output = Path(sys.argv[sys.argv.index("--") + 1])
output.write_text(json.dumps(results, indent=2) + "\n")
