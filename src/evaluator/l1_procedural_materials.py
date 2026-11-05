"""Inspect reachable appearance dependencies in the currently evaluated frame.

Runs inside the trusted Blender inspector; never reads image pixels or candidate
metadata. A procedural shader is not necessarily the *right* shader. This audit
only establishes the separate no-bitmap/assigned-material contract. Disconnected
nodes and unused material slots are not rendering dependencies. Connected mix
branches are conservatively included, even when a constant factor selects one.
"""
from __future__ import annotations

PROTOCOL = "l1-procedural-materials-v1"
_BITMAP_NODES = {
    "ShaderNodeTexImage", "ShaderNodeTexEnvironment", "GeometryNodeImageTexture",
    "GeometryNodeImageInfo", "GeometryNodeInputImage", "CompositorNodeImage",
    "CompositorNodeMovieClip",
}


class MaterialAudit:
    def __init__(self, *, max_nodes=50000, max_depth=64):
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.visited = 0
        self.material_uses = 0
        self.violations = []
        self.unknown = []
        self.roots = []
        self._active = set()
        self._done = set()
        self._scene = None
        self._root_inputs = {}

    def issue(self, owner, code, node=None, *, unknown=False):
        row = {"owner": owner, "code": code}
        if node is not None:
            row.update(node=node.name, node_type=node.bl_idname)
        target = self.unknown if unknown else self.violations
        if row not in target:
            target.append(row)

    @staticmethod
    def matching(sockets, source):
        # Group interface identifiers survive socket renames and repeated names.
        identifier = getattr(source, "identifier", None)
        matches = [s for s in sockets if identifier and s.identifier == identifier]
        return matches[0] if len(matches) == 1 else None

    def input(self, socket, context, owner, depth):
        links = [link for link in socket.links if not getattr(link, "is_muted", False)]
        if links:
            for link in links:
                self.output(link.from_socket, context, owner, depth + 1)
        else:
            value = getattr(socket, "default_value", None)
            if getattr(getattr(value, "bl_rna", None), "identifier", None) in {
                "Image", "MovieClip",
            }:
                self.issue(owner, "BITMAP_SOCKET", socket.node)

    def output(self, socket, context, owner, depth):
        node = socket.node
        key = (owner, tuple(n.as_pointer() for n in context), socket.as_pointer())
        if key in self._done:
            return
        if key in self._active or depth > self.max_depth or self.visited >= self.max_nodes:
            self.issue(owner, "GRAPH_CYCLE_OR_LIMIT", node, unknown=True)
            return
        self._active.add(key)
        self.visited += 1
        try:
            if node.mute:
                for link in node.internal_links:
                    if link.to_socket == socket:
                        self.input(link.from_socket, context, owner, depth + 1)
                return
            if node.bl_idname in _BITMAP_NODES or getattr(node, "image", None) is not None:
                self.issue(owner, "BITMAP_NODE", node)
            if getattr(node, "clip", None) is not None:
                self.issue(owner, "MOVIE_CLIP_NODE", node)
            if node.bl_idname == "CompositorNodeRLayers" and (
                getattr(node, "scene", None) not in (None, self._scene)
                or getattr(node, "layer", "") not in ("", self._view_layer)
            ):
                self.issue(owner, "OTHER_SCENE_OR_LAYER_NOT_INSPECTED", node, unknown=True)
            texture = getattr(node, "texture", None)
            if texture is not None and getattr(texture, "type", None) == "IMAGE":
                self.issue(owner, "BITMAP_TEXTURE", node)
            if node.bl_idname == "ShaderNodeScript":
                self.issue(owner, "UNINSPECTED_SHADER_SCRIPT", node, unknown=True)
            if node.type == "GROUP":
                tree = node.node_tree
                outputs = self.active_outputs(tree, "GROUP_OUTPUT") if tree else []
                if len(outputs) != 1:
                    self.issue(owner, "GROUP_OUTPUT_UNAVAILABLE", node, unknown=True)
                    return
                internal = self.matching(outputs[0].inputs, socket)
                if internal is None:
                    self.issue(owner, "GROUP_SOCKET_UNAVAILABLE", node, unknown=True)
                else:
                    self.input(internal, (*context, node), owner, depth + 1)
                return
            if node.type == "GROUP_INPUT":
                if context:
                    outer = self.matching(context[-1].inputs, socket)
                    if outer is None:
                        self.issue(owner, "GROUP_INPUT_UNAVAILABLE", node, unknown=True)
                    else:
                        self.input(outer, context[:-1], owner, depth + 1)
                else:
                    value = self._root_inputs.get(owner, {}).get(socket.identifier)
                    if getattr(getattr(value, "bl_rna", None), "identifier", None) == "Image":
                        self.issue(owner, "BITMAP_GROUP_INPUT", node)
                return
            for value in node.inputs:
                if getattr(value, "enabled", True):
                    self.input(value, context, owner, depth + 1)
        finally:
            self._active.remove(key)
            self._done.add(key)

    @staticmethod
    def active_outputs(tree, kind):
        return [n for n in tree.nodes if n.type == kind
                and getattr(n, "is_active_output", True)]

    def tree(self, tree, owner, kind, *, root_inputs=None):
        self._root_inputs[owner] = root_inputs or {}
        outputs = self.active_outputs(tree, kind)
        # Engine-specific output variants are all checked. This errs on the
        # conservative side instead of accidentally accepting an EEVEE bitmap.
        if not outputs:
            self.issue(owner, "ACTIVE_OUTPUT_UNAVAILABLE", unknown=True)
            return
        self.roots.append(owner)
        for node in outputs:
            for socket in node.inputs:
                if getattr(socket, "enabled", True):
                    self.input(socket, (), owner, 0)

    def datablock(self, block, owner, kind):
        if block is not None and getattr(block, "use_nodes", False):
            tree = getattr(block, "node_tree", None)
            if tree is None:
                self.issue(owner, "NODE_TREE_UNAVAILABLE", unknown=True)
            else:
                self.tree(tree, owner, kind)

    def materials(self, materials, used_slots, owner):
        for index in sorted(used_slots):
            material = materials[index] if 0 <= index < len(materials) else None
            label = f"{owner}/slot:{index}"
            self.material_uses += 1
            if material is None:
                self.issue(label, "UNASSIGNED_SURFACE")
            else:
                self.datablock(material, label, "OUTPUT_MATERIAL")

    def scene(self, scene, render_names, view_layer):
        self._scene = scene
        self._view_layer = view_layer.name
        self.datablock(scene.world, "world", "OUTPUT_WORLD")
        for obj in scene.objects:
            if obj.name not in render_names:
                continue
            if obj.type == "LIGHT":
                self.datablock(obj.data, f"light:{obj.name}", "OUTPUT_LIGHT")
            for modifier in obj.modifiers:
                if not modifier.show_render:
                    continue
                label = f"object:{obj.name}/modifier:{modifier.name}"
                texture = getattr(modifier, "texture", None)
                if texture is not None and getattr(texture, "type", None) == "IMAGE":
                    self.issue(label, "BITMAP_MODIFIER")
                if modifier.type == "NODES" and modifier.node_group is not None:
                    if hasattr(modifier, "properties"):
                        # Blender 5.2 stores interface values in RNA socket
                        # wrappers; older releases use modifier IDProperties.
                        inputs = modifier.properties.inputs
                        values = {
                            item.identifier: getattr(getattr(inputs, item.identifier, None), "value", None)
                            for item in modifier.node_group.interface.items_tree
                            if item.item_type == "SOCKET" and item.in_out == "INPUT"
                        }
                    else:
                        values = dict(modifier.items())
                    self.tree(modifier.node_group, label, "GROUP_OUTPUT",
                              root_inputs=values)
        if scene.render.use_compositing:
            tree = getattr(scene, "compositing_node_group", None)
            if tree is not None:
                self.tree(tree, "compositor", "GROUP_OUTPUT")
            elif not hasattr(scene, "compositing_node_group") and getattr(scene, "use_nodes", False):
                tree = getattr(scene, "node_tree", None)
                if tree is None:
                    self.issue("compositor", "COMPOSITOR_TREE_UNAVAILABLE", unknown=True)
                else:
                    self.tree(tree, "compositor", "COMPOSITE")
        # This inspector evaluates one layer. Other enabled layers and linked
        # Render Layers scenes need independent inspection before acceptance.
        if any(layer != view_layer and layer.use for layer in scene.view_layers):
            self.issue("scene", "OTHER_RENDER_LAYERS_NOT_INSPECTED", unknown=True)
        if scene.render.use_sequencer and scene.sequence_editor is not None:
            editor = scene.sequence_editor
            strips = getattr(editor, 'strips', getattr(editor, 'sequences', None))
            if strips is None or len(strips):
                # Scene/strip nesting and effect blending need a separate
                # output dependency walk. Do not certify no-bitmap merely
                # because the material/world node trees are procedural.
                self.issue('sequencer', 'SEQUENCER_OUTPUT_NOT_INSPECTED', unknown=True)

    def result(self, *, frame):
        if not self.material_uses:
            self.issue("scene", "NO_SURFACE_MATERIAL_EVIDENCE", unknown=True)
        status = "failed" if self.violations else "not_measurable" if self.unknown else "passed"
        return {
            "protocol": PROTOCOL, "status": status, "passed": status == "passed",
            "frame": frame, "material_uses": self.material_uses, "visited_nodes": self.visited,
            "roots": self.roots, "violations": self.violations, "unknown": self.unknown,
            "scope": "assigned_surfaces_and_reachable_appearance_dependencies_at_inspected_frame",
            "not_assessed": ["correct_colors_or_bsdf", "uninspected_frames", "shader_script_execution"],
        }
