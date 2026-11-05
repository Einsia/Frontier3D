"""Deterministic world-space L1 surface comparison of evaluator-owned meshes.

Distances are to triangle surfaces, not nearest vertices. No ICP, scaling or
per-part alignment is performed. Sampled maxima are diagnostics, not a claim
that the exact continuous Hausdorff distance has been computed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


@dataclass
class SurfaceMesh:
    vertices: np.ndarray
    triangles: np.ndarray
    surface_only: bool = False
    source_triangle_count: int = field(init=False)
    source_triangle_indices: np.ndarray = field(init=False, repr=False)
    surface_diagnostics: dict = field(init=False)
    xyz: np.ndarray = field(init=False, repr=False)
    areas: np.ndarray = field(init=False, repr=False)
    centers: np.ndarray = field(init=False, repr=False)
    radii: np.ndarray = field(init=False, repr=False)
    tree: cKDTree = field(init=False, repr=False)

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=np.float64)
        triangles = np.asarray(self.triangles)
        if (
            self.vertices.ndim != 2
            or self.vertices.shape[1:] != (3,)
            or not len(self.vertices)
            or not np.isfinite(self.vertices).all()
            or triangles.ndim != 2
            or triangles.shape[1:] != (3,)
            or not len(triangles)
            or triangles.dtype.kind not in "iu"
            or (triangles < 0).any()
            or (triangles >= len(self.vertices)).any()
        ):
            raise ValueError("Invalid triangle surface")
        self.triangles = triangles.astype(np.int64)
        self.xyz = self.vertices[self.triangles]
        self.areas = (
            np.linalg.norm(
                np.cross(
                    self.xyz[:, 1] - self.xyz[:, 0], self.xyz[:, 2] - self.xyz[:, 0]
                ),
                axis=1,
            )
            / 2
        )
        self.source_triangle_count = len(self.triangles)
        self.source_triangle_indices = np.arange(len(self.triangles))
        self.surface_diagnostics = {'source_triangles': len(self.triangles), 'ignored_triangles': 0,
                                    'ignored_area_m2': 0., 'solid_validation': 'not_assessed'}
        if not np.isfinite(self.areas).all():
            raise ValueError("Degenerate or unbounded triangle surface")
        usable = self.areas > 1e-18
        if not usable.all():
            if not self.surface_only or not usable.any():
                raise ValueError("Degenerate or unbounded triangle surface")
            self.surface_diagnostics.update(ignored_triangles=int((~usable).sum()),
                                            ignored_area_m2=float(self.areas[~usable].sum()))
            self.source_triangle_indices = self.source_triangle_indices[usable]
            self.triangles = self.triangles[usable]
            self.xyz, self.areas = self.xyz[usable], self.areas[usable]
        if self.surface_only:
            used, inverse = np.unique(self.triangles, return_inverse=True)
            self.vertices = self.vertices[used]
            self.triangles = inverse.reshape(-1, 3)
        self.centers = self.xyz.mean(axis=1)
        self.radii = np.linalg.norm(self.xyz - self.centers[:, None, :], axis=2).max(
            axis=1
        )
        self.tree = cKDTree(self.centers)


def load_surface(record: dict, trusted_root: Path, *, surface_only=False) -> SurfaceMesh:
    """Bind data to its inspector hash and root; never load pickled objects."""
    if record.get("coordinate_space") != "world_metres":
        raise ValueError("Surface must retain world coordinates in metres")
    path = Path(record["path"])
    if path.is_symlink() or not path.resolve().is_relative_to(trusted_root.resolve()):
        raise ValueError("Mesh payload escapes trusted inspection output")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ValueError("Mesh payload hash mismatch")
    # Read the verified bytes, not a potentially replaced path.
    import io

    with np.load(io.BytesIO(content), allow_pickle=False) as data:
        if set(data.files) != {"vertices_m", "triangles"}:
            raise ValueError("Unexpected mesh payload members")
        return SurfaceMesh(data["vertices_m"], data["triangles"], surface_only=surface_only)


def _distances_to_triangles(point: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    a, b, c = triangles[:, 0], triangles[:, 1], triangles[:, 2]
    ab, ac, ap = b - a, c - a, point - a
    normal = np.cross(ab, ac)
    normal2 = np.einsum("ij,ij->i", normal, normal)
    plane_dot = np.einsum("ij,ij->i", ap, normal)
    projection = point - normal * (plane_dot / normal2)[:, None]
    projected = projection - a
    # Cross-product barycentrics avoid subtracting almost equal Gram products
    # for long, thin triangles.
    u = np.einsum("ij,ij->i", np.cross(projected, ac), normal) / normal2
    v = np.einsum("ij,ij->i", np.cross(ab, projected), normal) / normal2
    inside = (u >= 0) & (v >= 0) & (u + v <= 1)
    distance2 = np.where(inside, plane_dot * plane_dot / normal2, np.inf)
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        edge2 = np.einsum("ij,ij->i", edge, edge)
        t = np.clip(np.einsum("ij,ij->i", point - start, edge) / edge2, 0, 1)
        delta = point - start - t[:, None] * edge
        distance2 = np.minimum(distance2, np.einsum("ij,ij->i", delta, delta))
    return np.sqrt(np.maximum(distance2, 0))


def surface_distances(points: np.ndarray, target: SurfaceMesh) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
        raise ValueError("Distance query requires finite 3D points")
    result = []
    _, first = target.tree.query(points)
    max_radius = float(target.radii.max())
    for point, index in zip(points, first, strict=True):
        upper = float(_distances_to_triangles(point, target.xyz[[index]])[0])
        # A triangle with a closer point must have its center within this
        # radius by the triangle inequality. This is an exact broad phase.
        rounding = (
            32
            * np.finfo(float).eps
            * max(1, float(np.linalg.norm(point)), upper, max_radius)
        )
        indices = target.tree.query_ball_point(point, upper + max_radius + rounding)
        indices = np.asarray(indices, dtype=int)
        lower_bounds = (
            np.linalg.norm(target.centers[indices] - point, axis=1)
            - target.radii[indices]
        )
        selected = indices[lower_bounds <= upper + rounding]
        result.append(
            float(_distances_to_triangles(point, target.xyz[selected]).min())
            if len(selected)
            else upper
        )
    return np.asarray(result)


def sample_surface(mesh: SurfaceMesh, count: int, seed: int) -> np.ndarray:
    if type(count) is not int or count <= 0 or type(seed) is not int or seed < 0:
        raise ValueError("Positive sample count and nonnegative integer seed required")
    # A single N×3 draw guarantees smaller levels are prefixes of larger ones.
    values = np.random.default_rng(seed).random((count, 3))
    cumulative = np.cumsum(mesh.areas)
    indices = np.searchsorted(cumulative, values[:, 0] * cumulative[-1], side="right")
    triangles = mesh.xyz[np.minimum(indices, len(mesh.xyz) - 1)]
    u, v = np.sqrt(values[:, 1]), values[:, 2]
    return (
        (1 - u)[:, None] * triangles[:, 0]
        + (u * (1 - v))[:, None] * triangles[:, 1]
        + (u * v)[:, None] * triangles[:, 2]
    )


def compare_surfaces(
    left: SurfaceMesh,
    right: SurfaceMesh,
    *,
    levels=(256, 1024, 4096),
    seed=0,
    convergence_m=1e-5,
) -> dict:
    if (
        not levels
        or any(type(n) is not int or n <= 0 for n in levels)
        or list(levels) != sorted(set(levels))
        or not np.isfinite(convergence_m)
        or convergence_m <= 0
        or type(seed) is not int
        or seed < 0
    ):
        raise ValueError("Invalid surface convergence configuration")
    if np.array_equal(left.vertices, right.vertices) and np.array_equal(left.triangles, right.triangles):
        # Actual loaded world coordinates and connectivity establish equality;
        # filenames, object names, declared hashes or bounds alone never do.
        # Keep the existing multi-level convergence contract, but do not claim
        # random samples were drawn for this stronger exact-array observation.
        return {
            'method': 'identical_world_triangle_arrays_v1',
            'coordinate_space': 'world_metres', 'alignment': 'none', 'seed': seed,
            'levels': [{'samples_per_direction': 0, 'requested_samples_per_direction': count,
                        'chamfer_mean_m': 0.0, 'rms_m': 0.0, 'sampled_max_m': 0.0}
                       for count in levels],
            'convergence_m': convergence_m,
            'last_level_deltas': {'chamfer_mean_m': 0.0, 'rms_m': 0.0, 'sampled_max_m': 0.0} if len(levels) > 1 else None,
            'converged': len(levels) > 1,
            'continuous_surface_bound_m': 0.0,
            'left_bounds_m': [left.vertices.min(axis=0).tolist(), left.vertices.max(axis=0).tolist()],
            'right_bounds_m': [right.vertices.min(axis=0).tolist(), right.vertices.max(axis=0).tolist()],
            'limitations': ['Equality concerns these loaded triangle arrays only; no role, material or assembly verdict.'],
        }
    largest = levels[-1]
    a = surface_distances(sample_surface(left, largest, seed), right)
    b = surface_distances(sample_surface(right, largest, seed + 1), left)
    # Vertex and face-center sentinels improve detection of localized edits;
    # they do not bias the area-weighted Chamfer mean.
    sentinels_a = surface_distances(
        np.concatenate((left.vertices, left.centers)), right
    )
    sentinels_b = surface_distances(
        np.concatenate((right.vertices, right.centers)), left
    )
    sentinels_max = max(float(sentinels_a.max()), float(sentinels_b.max()))
    rows = []
    for count in levels:
        rows.append(
            {
                "samples_per_direction": count,
                "chamfer_mean_m": float((a[:count].mean() + b[:count].mean()) / 2),
                "rms_m": float(
                    np.sqrt(
                        (np.square(a[:count]).mean() + np.square(b[:count]).mean()) / 2
                    )
                ),
                "sampled_max_m": max(
                    float(a[:count].max()), float(b[:count].max()), sentinels_max
                ),
            }
        )
    deltas = (
        {
            key: abs(rows[-1][key] - rows[-2][key])
            for key in ("chamfer_mean_m", "rms_m", "sampled_max_m")
        }
        if len(rows) > 1
        else None
    )
    return {
        "method": "area_weighted_point_to_triangle_v1",
        "coordinate_space": "world_metres",
        "alignment": "none",
        "seed": seed,
        "levels": rows,
        "convergence_m": convergence_m,
        "last_level_deltas": deltas,
        "converged": deltas is not None and max(deltas.values()) <= convergence_m,
        "left_bounds_m": [
            left.vertices.min(axis=0).tolist(),
            left.vertices.max(axis=0).tolist(),
        ],
        "right_bounds_m": [
            right.vertices.min(axis=0).tolist(),
            right.vertices.max(axis=0).tolist(),
        ],
        "limitations": [
            "Finite-sample convergence is diagnostic, not a continuous Hausdorff bound.",
            "No alignment is applied; shape and placement changes are both visible.",
        ],
    }
