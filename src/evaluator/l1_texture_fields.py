"""Bounded, typed shader fields for trusted L1 surface observations.

No code evaluation or candidate imports. Unsupported nodes/color spaces must
remain unavailable, never become a constant/default material success.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np

MAX_PIXELS = 4_194_304
MAX_FIELD_DEPTH = 32


def linearize_rgba(values, *, color_space, image_is_float, alpha_mode="STRAIGHT"):
    """Decode supported RGB to scene-linear Rec.709; alpha is never gamma-corrected."""
    pixels = np.asarray(values, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[2] != 4 or not pixels.shape[0] or not pixels.shape[1] or pixels.shape[0] * pixels.shape[1] > MAX_PIXELS:
        raise ValueError("Invalid or oversized RGBA image")
    if not np.isfinite(pixels).all() or type(image_is_float) is not bool:
        raise ValueError("Invalid pixel values or image storage metadata")
    if not image_is_float and ((pixels < 0).any() or (pixels > 1).any()):
        raise ValueError('Byte image channels outside [0, 1]')
    if alpha_mode not in {"STRAIGHT", "CHANNEL_PACKED"}:
        raise ValueError("Premultiplied or ignored-alpha image semantics not supported")
    result = pixels.copy()
    if color_space == "sRGB" and not image_is_float:
        rgb = pixels[..., :3]
        # A byte sRGB image is bounded; negative/HDR sRGB needs another adapter.
        if (rgb < 0).any() or (rgb > 1).any():
            raise ValueError("Byte sRGB values outside [0, 1]")
        result[..., :3] = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    elif color_space not in {"Non-Color", "Linear Rec.709"}:
        raise ValueError("Uncalibrated texture color space or floating sRGB storage")
    return result.astype(np.float32)


def load_texture(record, trusted_root):
    if record.get("protocol") != "l1-texture-pixels-v1" or record.get("sampling") != "cycles_cpu_filter_then_decode_v1":
        raise ValueError("Invalid texture pixel protocol")
    path = Path(record["path"])
    root = Path(trusted_root).resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Texture pixel payload escapes trusted root")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ValueError("Texture pixel hash mismatch")
    with np.load(io.BytesIO(content), allow_pickle=False) as data:
        if set(data.files) != {"stored_rgba"}:
            raise ValueError("Unexpected texture pixel members")
        pixels = data["stored_rgba"]
    shape = pixels.shape
    if (pixels.dtype.kind != "f" or len(shape) != 3 or shape[2] != 4 or not shape[0] or not shape[1]
            or shape[0] * shape[1] > MAX_PIXELS or not np.isfinite(pixels).all()
            or record["size"] != [shape[1], shape[0]]):
        raise ValueError("Invalid texture dimensions or pixel values")
    metadata = {key: record[key] for key in ("color_space", "image_is_float", "alpha_mode")}
    # Validate supported metadata and the whole pixel range before sampling.
    linearize_rgba(pixels, **metadata)
    return {"pixels": pixels, **metadata}


def load_uv_layers(record, *, geometry_sha256, triangle_count, trusted_root):
    if record.get('protocol') != 'l1-surface-uv-v1' or record.get('status') != 'ok':
        raise ValueError('Invalid UV observation protocol')
    layers = record['layers']
    if not isinstance(layers, list) or len(layers) > 8 or type(triangle_count) is not int or triangle_count <= 0:
        raise ValueError('Invalid UV layer/triangle count')
    result = {}
    root = Path(trusted_root).resolve()
    for layer in layers:
        name = layer['name']
        if not isinstance(name, str) or not name or name in result or layer['geometry_sha256'] != geometry_sha256:
            raise ValueError('Duplicate, unnamed or incorrectly bound UV layer')
        path = Path(layer['path'])
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('UV payload escapes trusted root')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != layer['sha256']:
            raise ValueError('UV payload hash mismatch')
        with np.load(io.BytesIO(content), allow_pickle=False) as data:
            if set(data.files) != {'triangle_uv'}:
                raise ValueError('Unexpected UV payload members')
            values = data['triangle_uv']
        if values.dtype.kind != 'f' or values.shape != (triangle_count, 3, 2) or not np.isfinite(values).all():
            raise ValueError('Invalid UV payload shape or values')
        result[name] = values
    if record['default_layer'] is not None and record['default_layer'] not in result:
        raise ValueError('Default render UV layer is missing')
    return result


def sample_texture(pixels, uv, *, interpolation="Linear", extension="REPEAT",
                   color_space="Non-Color", image_is_float=False, alpha_mode="STRAIGHT", alpha_used=False):
    """Calibrated Cycles CPU lookup: filter stored byte sRGB, THEN decode RGB.

    This order is verified against the trusted emission oracle; pre-decoding
    texels gives visibly different values between texel centers.
    """
    pixels = np.asarray(pixels)
    uv = np.asarray(uv, dtype=np.float64)
    if pixels.ndim != 3 or pixels.shape[2] != 4 or not pixels.shape[0] or not pixels.shape[1] or not np.isfinite(pixels).all():
        raise ValueError("Invalid texture array")
    if not image_is_float and ((pixels < 0).any() or (pixels > 1).any()):
        raise ValueError('Byte image channels outside [0, 1]')
    if uv.ndim != 2 or uv.shape[1] != 2 or not len(uv) or not np.isfinite(uv).all() or (np.abs(uv) > 2 ** 30).any():
        raise ValueError("Invalid or excessive UV coordinates")
    if extension not in {"REPEAT", "EXTEND"} or interpolation not in {"Closest", "Linear"}:
        raise ValueError("Uncalibrated interpolation or extension")
    if type(alpha_used) is not bool:
        raise ValueError("Image Alpha output usage must be explicit")
    associated = alpha_mode == "STRAIGHT" and color_space != "Non-Color"
    if associated and image_is_float and np.any(pixels[..., 3] != 1):
        raise ValueError("Transparent floating-image association awaits calibration")
    if associated and np.any(pixels[..., 3] != 1):
        pixels = pixels.copy()
        pixels[..., :3] *= pixels[..., 3:4]
        if not image_is_float:
            # Measured byte-cache behavior: truncation, not round-to-nearest.
            pixels[..., :3] = np.floor(pixels[..., :3] * 255) / 255
    height, width = pixels.shape[:2]
    def fetch(x, y):
        if extension == "REPEAT":
            return pixels[y % height, x % width]
        return pixels[np.clip(y, 0, height - 1), np.clip(x, 0, width - 1)]
    coords = uv * np.array([width, height])
    if interpolation == "Closest":
        indices = np.floor(coords).astype(np.int64)
        sampled = fetch(indices[:, 0], indices[:, 1])
    else:
        coords -= .5
        indices = np.floor(coords).astype(np.int64)
        fraction = coords - indices
        x, y = indices[:, 0], indices[:, 1]
        u, v = fraction[:, 0, None], fraction[:, 1, None]
        sampled = ((1-u) * (1-v) * fetch(x, y) + u * (1-v) * fetch(x+1, y)
                   + (1-u) * v * fetch(x, y+1) + u * v * fetch(x+1, y+1))
    if not len(sampled):
        return np.empty((0, 4), dtype=np.float32)
    if associated and alpha_used:
        sampled = sampled.copy()
        sampled[:, :3] = np.divide(sampled[:, :3], sampled[:, 3:4],
                                  out=np.zeros_like(sampled[:, :3]), where=sampled[:, 3:4] != 0)
    if not image_is_float:
        # Convex interpolation can produce 1 + a few machine ulps even though
        # every stored byte is valid. Clamp only this arithmetic roundoff;
        # invalid stored texels were rejected before filtering, not hidden.
        epsilon = 32 * np.finfo(sampled.dtype).eps
        if (sampled < -epsilon).any() or (sampled > 1 + epsilon).any():
            raise ValueError('Byte filtering produced out-of-range channels')
        sampled = np.clip(sampled, 0, 1)
    return linearize_rgba(sampled[:, None, :], color_space=color_space,
                          image_is_float=image_is_float, alpha_mode=alpha_mode)[:, 0, :]


def evaluate_field(expression, *, uv_fields, textures, count, depth=0):
    """Return N×channels from a small typed expression tree, never Python eval."""
    if depth > MAX_FIELD_DEPTH or type(count) is not int or count <= 0:
        raise ValueError("Shader field depth/count limit")
    def evaluate(value):
        return evaluate_field(value, uv_fields=uv_fields, textures=textures, count=count, depth=depth+1)
    if not isinstance(expression, dict):
        value = np.asarray(expression)
        if value.dtype.kind not in "fiu" or value.ndim > 1 or not value.size or value.size > 4 or not np.isfinite(value).all():
            raise ValueError("Invalid constant shader field")
        return np.broadcast_to(value.reshape(1, -1), (count, value.size))
    operation = expression.get("op")
    if operation == "uv":
        values = np.asarray(uv_fields[expression["layer"]], dtype=float)
        if values.shape != (count, 2) or not np.isfinite(values).all():
            raise ValueError("Missing or invalid bound UV field")
        return np.column_stack((values, np.zeros(count)))
    if operation == "image":
        vector = evaluate(expression["vector"])
        if vector.shape != (count, 3):
            raise ValueError("Texture coordinates require a vector field")
        texture = textures[expression["image"]]
        result = sample_texture(texture["pixels"], vector[:, :2],
                                **{key: texture[key] for key in ("color_space", "image_is_float", "alpha_mode")},
                                alpha_used=expression["alpha_used"],
                                interpolation=expression["interpolation"], extension=expression["extension"])
        if expression["channel"] == "Color":
            return result[:, :3]
        if expression["channel"] == "Alpha":
            return result[:, 3:4]
        raise ValueError("Unsupported image output channel")
    if operation == "separate":
        values = evaluate(expression["value"])
        channel = expression["channel"]
        if type(channel) is not int or not 0 <= channel < values.shape[1]:
            raise ValueError("Invalid separated channel")
        return values[:, channel:channel+1]
    if operation == "math":
        inputs = expression["inputs"]
        if not isinstance(inputs, list) or len(inputs) != 2:
            raise ValueError("Binary math field requires two inputs")
        a, b = map(evaluate, inputs)
        if a.shape != (count, 1) or b.shape != (count, 1) or type(expression["clamp"]) is not bool:
            raise ValueError("Math inputs must be scalar fields")
        name = expression["operation"]
        with np.errstate(over="raise", invalid="raise"):
            if name == "MULTIPLY":
                result = a * b
            elif name == "ADD":
                result = a + b
            elif name == "SUBTRACT":
                result = a - b
            elif name == "DIVIDE":
                result = np.divide(a, b, out=np.zeros_like(a, dtype=float), where=b != 0)
            else:
                raise ValueError("Unsupported scalar math operation")
        if expression["clamp"]:
            result = np.clip(result, 0, 1)
        if not np.isfinite(result).all():
            raise ValueError("Nonfinite shader field result")
        return result
    raise ValueError("Unsupported shader field expression")
