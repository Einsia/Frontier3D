"""Blender-side effective constant shader evidence; no candidate imports.

This observes a declared Principled subset, not arbitrary shader equivalence.
Reachable texture metadata is diagnostic until pixel/UV equivalence is supported.
"""

from __future__ import annotations

import hashlib
import math

PROTOCOL = "l1-material-surface-v1"


def _number(value):
    if isinstance(value, (int, float)):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite shader parameter")
        return result
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError("Nonfinite shader vector")
    return result


def _constant(socket, seen=None):
    seen = set() if seen is None else seen
    if not socket.is_linked:
        return _number(socket.default_value)
    if len(socket.links) != 1:
        raise ValueError("Multiple shader input links")
    link = socket.links[0]
    node = link.from_node
    if node.as_pointer() in seen or node.mute:
        raise ValueError("Cyclic or muted shader graph is unsupported")
    seen = seen | {node.as_pointer()}
    if node.type == "REROUTE":
        return _constant(node.inputs[0], seen)
    if node.type not in {"RGB", "VALUE"} or link.from_socket.type != socket.type:
        raise ValueError("Nonconstant input or implicit socket conversion requires graph evaluation")
    return _number(link.from_socket.default_value)


def _dependencies(output):
    seen, pending, images = set(), [output], []
    while pending:
        node = pending.pop()
        if node.as_pointer() in seen:
            continue
        seen.add(node.as_pointer())
        if node.type == "TEX_IMAGE":
            image = node.image
            item = {"node": node.name, "status": "not_measurable"}
            if image is None:
                item["reason"] = "Image texture has no image"
            else:
                item.update(image=image.name, source=image.source, filepath=image.filepath,
                            colorspace=image.colorspace_settings.name,
                            interpolation=node.interpolation, projection=node.projection,
                            extension=node.extension,
                            reason="Pixel content, reachable mapping and UV surface equivalence not assessed")
                # Never resolve/read arbitrary external candidate paths here.
                if image.packed_file is not None:
                    item["packed_sha256"] = hashlib.sha256(image.packed_file.data).hexdigest()
            images.append(item)
        pending.extend(link.from_node for socket in node.inputs for link in socket.links)
    return images


def describe_material(material):
    if material is None:
        return {"status": "ok", "kind": "unassigned", "parameters": {}, "flags": {}}
    result = {"status": "not_measurable", "material": material.name, "dependencies": []}
    try:
        if not material.use_nodes or material.node_tree is None:
            raise ValueError("Non-node shader semantics require a separate material adapter")
        outputs = [node for node in material.node_tree.nodes if node.type == "OUTPUT_MATERIAL"
                   and node.is_active_output and node.target == "ALL"]
        if len(outputs) != 1:
            raise ValueError("One active all-engine output required")
        output = outputs[0]
        result["dependencies"] = _dependencies(output)
        if output.inputs["Volume"].is_linked or output.inputs["Displacement"].is_linked:
            raise ValueError("Volume/displacement shader equivalence not assessed")
        links = output.inputs["Surface"].links
        if len(links) != 1 or links[0].from_node.type != "BSDF_PRINCIPLED" or links[0].from_node.mute:
            raise ValueError("Direct Principled surface output required")
        shader = links[0].from_node
        parameters = {}
        for socket in shader.inputs:
            if not socket.enabled:
                continue
            value = _constant(socket)
            # Principled color inputs consume RGB; opacity is the separate
            # Alpha socket. A color picker's fourth channel is not opacity.
            if socket.type == "RGBA":
                if not isinstance(value, list) or len(value) != 4:
                    raise ValueError("Invalid constant color socket shape")
                value = value[:3]
            elif socket.type == "VALUE" and not isinstance(value, float):
                raise ValueError("Implicit vector-to-value conversion is unsupported")
            parameters[socket.name] = value
        flags = {key: getattr(material, key) for key in (
            "use_backface_culling", "surface_render_method", "use_transparent_shadow",
        ) if hasattr(material, key)}
        flags.update(distribution=shader.distribution, subsurface_method=shader.subsurface_method)
        result.update(status="ok", kind="constant_principled", parameters=parameters, flags=flags)
    except (AttributeError, TypeError, ValueError) as error:
        result["reason"] = str(error)
    return result


def capture_materials(materials):
    slots = [describe_material(material) for material in materials]
    # A material-less mesh has the same implicit assignment on all polygons.
    return {"protocol": PROTOCOL, "slots": slots or [describe_material(None)],
            "scope": "constant_principled_parameters_and_surface_assignment",
            "not_assessed": ["general_shader_graphs", "texture_pixels_and_uv_mapping", "volumes_and_displacement"]}
