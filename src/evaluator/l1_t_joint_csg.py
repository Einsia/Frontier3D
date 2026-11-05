"""Code013 nominal analytic CSG: guarded box enclosures, NOT surface distance.

Negative implicit values denote solid interiors. Min/max Boolean composition
preserves signs and the 1-Lipschitz property, but its magnitude is not an
Euclidean distance upper bound. Initial here is a PUBLIC CONSTRUCTION MODEL;
it never replaces the authoritative initial mesh in preservation checks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .l1_t_joint_paths import validate_design

GUARD_M = 8e-9
WORLD_LIMIT_M = 1.


def _vector(value, size):
    raw = np.asarray(value)
    if (raw.dtype.kind not in 'fiu' or raw.shape != (size,)
            or any(isinstance(v, (bool, np.bool_)) for v in np.asarray(value, dtype=object).flat)):
        raise ValueError('Expected finite numeric coordinates, without booleans')
    result = raw.astype(float)
    if not np.isfinite(result).all() or (np.abs(result) > WORLD_LIMIT_M).any():
        raise ValueError('CSG prototype supports world coordinates within one metre')
    return result


@dataclass(frozen=True)
class Box:
    lower: tuple[float, float, float]
    upper: tuple[float, float, float]

    def __post_init__(self):
        low, high = _vector(self.lower, 3), _vector(self.upper, 3)
        if (low > high).any():
            raise ValueError('Reversed spatial box')
        object.__setattr__(self, 'lower', tuple(low))
        object.__setattr__(self, 'upper', tuple(high))


@dataclass(frozen=True)
class Cylinder:
    axis: int
    center: tuple[float, float, float]
    radius: float
    span: tuple[float, float]

    def __post_init__(self):
        if type(self.axis) is not int or self.axis not in (0, 1, 2):
            raise ValueError('Only explicit world X/Y/Z cylinder axes are supported')
        center, span = _vector(self.center, 3), _vector(self.span, 2)
        if (type(self.radius) not in (int, float) or not np.isfinite(self.radius)
                or not 32*GUARD_M < self.radius <= WORLD_LIMIT_M
                or span[1]-span[0] <= 32*GUARD_M):
            raise ValueError('Invalid finite cylinder dimensions')
        object.__setattr__(self, 'center', tuple(center))
        object.__setattr__(self, 'span', tuple(span))


@dataclass(frozen=True)
class Boolean:
    operation: str
    left: Cylinder | Boolean
    right: Cylinder | Boolean

    def __post_init__(self):
        if self.operation not in ('union', 'intersection', 'difference'):
            raise ValueError('Unknown CSG Boolean operation')
        if not all(isinstance(v, (Cylinder, Boolean)) for v in (self.left, self.right)):
            raise ValueError('CSG children must be validated immutable primitives or nodes')


def field_interval(node, box):
    """Enclose the implicit value of EVERY point of the closed spatial box.

    Primitive arithmetic gets an outward 8 nm guard, with coordinates bounded
    to +/-1 m. This is a float64 guarded enclosure, not exact CAD arithmetic.
    Correlation loss at Boolean intersections can only make it inconclusive.
    """
    if not isinstance(box, Box):
        raise TypeError('Expected validated spatial Box')
    if isinstance(node, Cylinder):
        low, high = np.asarray(box.lower), np.asarray(box.upper)
        axes = [i for i in range(3) if i != node.axis]
        near = np.maximum(np.maximum(low[axes]-np.asarray(node.center)[axes],
                                     np.asarray(node.center)[axes]-high[axes]), 0.)
        far = np.maximum(np.abs(low[axes]-np.asarray(node.center)[axes]),
                         np.abs(high[axes]-np.asarray(node.center)[axes]))
        lower = max(float(np.linalg.norm(near))-node.radius,
                    node.span[0]-high[node.axis], low[node.axis]-node.span[1])
        upper = max(float(np.linalg.norm(far))-node.radius,
                    node.span[0]-low[node.axis], high[node.axis]-node.span[1])
        return float(np.nextafter(lower-GUARD_M, -np.inf)), float(np.nextafter(upper+GUARD_M, np.inf))
    if not isinstance(node, Boolean):
        raise TypeError('Expected a validated CSG node')
    a, b = field_interval(node.left, box), field_interval(node.right, box)
    if node.operation == 'union':
        return min(a[0], b[0]), min(a[1], b[1])
    if node.operation == 'difference':
        b = (-b[1], -b[0])
    return max(a[0], b[0]), max(a[1], b[1])


def classify_box(node, box):
    lower, upper = field_interval(node, box)
    return {'classification': 'inside' if upper < 0 else 'outside' if lower > 0 else 'undetermined',
            'implicit_interval_m': [lower, upper], 'numeric_guard_m': GUARD_M,
            'is_euclidean_distance_interval': False}


def symmetric_difference(a, b):
    return Boolean('union', Boolean('difference', a, b), Boolean('difference', b, a))


def target_model(design):
    """Nominal public analytic construction only: independent tolerances NOT fitted.

    Bore extensions end in known common void/exterior regions. Extending the
    horizontal bore all the way across the NEGATIVE main wall is forbidden.
    """
    validate_design(design)
    d = design
    z, end = d['branch_z_m'], d['branch_end_x_m']
    main = Cylinder(2, (0., 0., 0.), d['main_outer_radius_m'], (0., d['main_height_m']))
    branch = Cylinder(0, (0., 0., z), d['branch_outer_radius_m'], (0., end))
    main_bore = Cylinder(2, (0., 0., 0.), d['main_inner_radius_m'], (-.002, d['main_height_m']+.002))
    branch_bore = Cylinder(0, (0., 0., z), d['branch_inner_radius_m'], (-.002, end+.002))
    socket = Cylinder(0, (0., 0., z), d['socket_radius_m'], (end-d['socket_depth_m'], end+.002))
    holes = Cylinder(1, (d['radial_x_m'], 0., z), d['radial_radius_m'],
                     (-d['branch_outer_radius_m']-.002, d['branch_outer_radius_m']+.002))
    outer = Boolean('union', main, branch)
    cavities = Boolean('union', Boolean('union', main_bore, branch_bore), Boolean('union', socket, holes))
    return Boolean('difference', outer, cavities)


def public_initial_model():
    """Analytic reading of environment/input/initial.py, NOT initial.blend."""
    outer = Boolean('union', Cylinder(2, (0., 0., 0.), .012, (0., .050)),
                    Cylinder(0, (0., 0., .025), .010, (0., .030)))
    void = Boolean('union', Cylinder(2, (0., 0., 0.), .008, (-.002, .052)),
                   Cylinder(0, (0., 0., .025), .006, (-.002, .032)))
    return Boolean('difference', outer, void)
