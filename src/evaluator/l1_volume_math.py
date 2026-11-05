"""Double-precision winding classification for validated closed L1 meshes.

No Blender or SciPy dependency: also imported inside the independent worker.
Ambiguous winding values remain unknown instead of being rounded into a pass.
"""

from __future__ import annotations

import numpy as np


def winding_classification(
    vertices, triangles, points, *, tolerance=1e-5, epsilon_m=1e-9
) -> np.ndarray:
    vertices, points = (
        np.asarray(vertices, dtype=float),
        np.asarray(points, dtype=float),
    )
    triangles = np.asarray(triangles)
    if (
        vertices.ndim != 2
        or vertices.shape[1:] != (3,)
        or not np.isfinite(vertices).all()
        or points.ndim != 2
        or points.shape[1:] != (3,)
        or not np.isfinite(points).all()
        or triangles.ndim != 2
        or triangles.shape[1:] != (3,)
        or triangles.dtype.kind not in "iu"
        or not len(triangles)
        or not len(vertices)
        or (triangles < 0).any()
        or (triangles >= len(vertices)).any()
        or not np.isfinite(tolerance)
        or not 0 < tolerance < 0.5
        or not np.isfinite(epsilon_m)
        or epsilon_m <= 0
    ):
        raise ValueError(
            "Winding requires finite vertices, triangle indices and points"
        )
    xyz = vertices[triangles]
    normals = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    normal_lengths = np.linalg.norm(normals, axis=1)
    if np.any(normal_lengths <= 1e-18):
        raise ValueError("Degenerate triangles cannot classify solid occupancy")
    result = np.full(len(points), -1, dtype=np.int8)
    outside = np.any(
        (points < vertices.min(axis=0) - epsilon_m)
        | (points > vertices.max(axis=0) + epsilon_m),
        axis=1,
    )
    result[outside] = 0
    indices = np.flatnonzero(~outside)
    batch = max(1, min(64, 200000 // len(triangles)))
    for start in range(0, len(indices), batch):
        subset = indices[start : start + batch]
        delta = xyz[None, :, :, :] - points[subset, None, None, :]
        a, b, c = delta[:, :, 0], delta[:, :, 1], delta[:, :, 2]
        la, lb, lc = (
            np.linalg.norm(a, axis=2),
            np.linalg.norm(b, axis=2),
            np.linalg.norm(c, axis=2),
        )
        numerator = np.einsum("ijk,ijk->ij", a, np.cross(b, c))
        denominator = (
            la * lb * lc
            + np.einsum("ijk,ijk->ij", a, b) * lc
            + np.einsum("ijk,ijk->ij", b, c) * la
            + np.einsum("ijk,ijk->ij", c, a) * lb
        )
        winding = np.abs(np.arctan2(numerator, denominator).sum(axis=1) / (2 * np.pi))
        result[subset[winding <= tolerance]] = 0
        result[subset[np.abs(winding - 1) <= tolerance]] = 1
        near_plane = np.abs(numerator) <= epsilon_m * normal_lengths[None, :]
        if near_plane.any():
            inside_triangle = near_plane.copy()
            for p, q in ((a, b), (b, c), (c, a)):
                side = np.einsum("ijk,jk->ij", np.cross(q - p, -p), normals)
                slack = (
                    epsilon_m * normal_lengths[None, :] * np.linalg.norm(q - p, axis=2)
                )
                inside_triangle &= side >= -slack
            result[subset[inside_triangle.any(axis=1)]] = -1
    return result
