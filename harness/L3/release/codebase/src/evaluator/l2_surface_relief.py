"""Measured depressions and terrain relief from complete, opaque world geometry.

Vertical queries use every triangle intersecting a spatial bucket, not a sampled
mesh. The query locations are finite and public; they do not certify continuous
volume, semantic identity, arbitrary overhangs or physical stability.
"""
import numpy as np
from scipy.spatial import ConvexHull, QhullError

from .l2_reference_numeric import groups, triangles
from .metrics import MissingEvidence, _register


class VerticalSurface:
    """Exact top intersection at nominated XY points, with a bounded full index."""
    def __init__(self, surface):
        surface = np.asarray(surface, float)
        if len(surface) > 1_000_000:
            raise MissingEvidence('Relief measurement exceeds one million complete triangles')
        edge1 = surface[:, 1] - surface[:, 0]; edge2 = surface[:, 2] - surface[:, 0]
        det = edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0]
        selected = np.abs(det) > 1e-14
        if not selected.any():
            raise MissingEvidence('No surface with a nondegenerate horizontal projection')
        self.surface = surface[selected]; self.a = edge1[selected]; self.b = edge2[selected]
        self.det = det[selected]
        low = self.surface[:, :, :2].min(axis=1); high = self.surface[:, :, :2].max(axis=1)
        self.low = low.min(axis=0); self.high = high.max(axis=0)
        self.cell = np.maximum((self.high - self.low) / 32, 1e-9)
        start = np.clip(np.floor((low - self.low) / self.cell).astype(int), 0, 31)
        end = np.clip(np.floor((high - self.low) / self.cell).astype(int), 0, 31)
        if np.prod(end - start + 1, axis=1).sum() > 4_000_000:
            raise MissingEvidence('Full vertical surface index exceeds four million references')
        buckets = [[] for _ in range(32 * 32)]
        for index, (a, b) in enumerate(zip(start, end)):
            for y in range(a[1], b[1] + 1):
                for x in range(a[0], b[0] + 1):
                    buckets[y * 32 + x].append(index)
        self.buckets = [np.asarray(b, dtype=np.int32) for b in buckets]

    def top(self, points, ceiling=None):
        heights = np.full(len(points), np.nan)
        ceilings = np.broadcast_to(np.inf if ceiling is None else ceiling, (len(points),))
        for i, point in enumerate(np.asarray(points, float)):
            if np.any(point < self.low - 1e-9) or np.any(point > self.high + 1e-9):
                continue
            x, y = np.clip(np.floor((point - self.low) / self.cell).astype(int), 0, 31)
            indices = self.buckets[y * 32 + x]
            if not len(indices):
                continue
            offset = point - self.surface[indices, 0, :2]
            a, b, det = self.a[indices], self.b[indices], self.det[indices]
            u = (offset[:, 0] * b[:, 1] - offset[:, 1] * b[:, 0]) / det
            v = (a[:, 0] * offset[:, 1] - a[:, 1] * offset[:, 0]) / det
            inside = (u >= -1e-8) & (v >= -1e-8) & (u + v <= 1 + 1e-8)
            z = self.surface[indices, 0, 2] + u * a[:, 2] + v * b[:, 2]
            inside &= z <= ceilings[i] + 1e-9
            if inside.any():
                heights[i] = float(z[inside].max())
        return heights


def footprint(surface):
    xy = np.unique(surface[:, :, :2].reshape(-1, 2), axis=0)
    try:
        hull = xy[ConvexHull(xy).vertices]
    except QhullError:
        raise MissingEvidence('A nondegenerate depression footprint is required') from None
    best = None
    for edge in np.roll(hull, -1, axis=0) - hull:
        axis = edge / np.linalg.norm(edge)
        rotation = np.array([axis, [-axis[1], axis[0]]]).T
        projected = hull @ rotation; low = projected.min(axis=0); high = projected.max(axis=0)
        area = float(np.prod(high - low))
        if best is None or area < best[0] - 1e-12:
            best = area, rotation, low, high
    _, rotation, low, high = best
    return (low + high) / 2 @ rotation.T, (high - low) / 2, rotation


def scene_surface(evidence):
    surfaces = [triangles(obj, evidence) for obj in evidence['scene']['objects'].values()
                if obj.get('type') == 'MESH' and obj.get('visible_render') and obj.get('faces')]
    if not surfaces:
        raise MissingEvidence('Complete visible scene geometry is required')
    return VerticalSurface(np.concatenate(surfaces))


def plane(points, heights):
    center = points.mean(axis=0); scale = np.maximum(np.ptp(points, axis=0), 1e-6)
    matrix = np.column_stack(((points - center) / scale, np.ones(len(points))))
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, heights, rcond=None)
    if rank != 3:
        raise MissingEvidence('Local ground observations do not determine a plane')
    def predict(xy):
        return np.column_stack(((xy - center) / scale, np.ones(len(xy)))) @ coefficients
    return predict, heights - predict(points)


@_register('l2_surface_depression', 'role support_role directions inner_fraction rim_fractions outside_fraction min_depth_m min_rim_height_m required_fraction occlusion_tolerance_m')
def depression(check, evidence, spec):
    p = check.params
    surroundings = VerticalSurface(np.concatenate([s for _, s in groups(evidence, p['support_role'])]))
    visible = scene_surface(evidence); rows = []
    angles = np.arange(p['directions']) * (2 * np.pi / p['directions'])
    directions = np.column_stack((np.cos(angles), np.sin(angles)))
    for group, surface in groups(evidence, p['role']):
        center, radii, rotation = footprint(surface)
        if min(radii) <= 1e-6:
            raise MissingEvidence('Depression footprint has zero width')
        # Outside observations lie beyond every edge of the oriented footprint.
        square = directions / np.max(np.abs(directions), axis=1)[:, None]
        outer_xy = center + (square * radii * p['outside_fraction']) @ rotation.T
        outer_z = surroundings.top(outer_xy)
        if not np.isfinite(outer_z).all():
            raise MissingEvidence('Complete surrounding support ring is required')
        ground, ground_residual = plane(outer_xy, outer_z)
        inside_xy = center + (directions * radii * p['inner_fraction']) @ rotation.T
        own = VerticalSurface(surface); inner_z = own.top(inside_xy); global_z = visible.top(inside_xy)
        rim_xy = np.concatenate([center + (directions * radii * f) @ rotation.T for f in p['rim_fractions']])
        rim_z = own.top(rim_xy).reshape(len(p['rim_fractions']), -1)
        rim_ground = ground(rim_xy).reshape(rim_z.shape)
        rim_residual = np.where(np.isfinite(rim_z), rim_z - rim_ground, -np.inf).max(axis=0)
        # Matching the full-scene top hit rejects a covered hole or a labeled
        # negative-height proxy below an unmodified floor.
        finite = np.isfinite(inner_z) & np.isfinite(global_z)
        exposed = finite & (np.abs(inner_z - global_z) <= p['occlusion_tolerance_m'])
        depth = ground(inside_xy) - inner_z
        below_rim = rim_residual + depth
        valid = (exposed & (depth >= p['min_depth_m']) & (below_rim >= p['min_depth_m'])
                 & (rim_residual >= p['min_rim_height_m']))
        fraction = float(valid.mean())
        rows.append({'entity': group['id'], 'passed': fraction >= p['required_fraction'],
            'depressed_exposed_fraction': fraction, 'exposed_fraction': float(exposed.mean()),
            'depth_below_local_ground_m': [float(v) if np.isfinite(v) else None for v in depth],
            'rim_height_above_local_ground_m': [float(v) if np.isfinite(v) else None for v in rim_residual],
            'surrounding_plane_max_residual_m': float(np.max(np.abs(ground_residual))),
            'footprint_dimensions_m': (2 * radii).tolist(), 'directions': p['directions']})
    return float(all(r['passed'] for r in rows)), {'entities': rows,
        'scope': 'Finite top-down probes on complete opaque geometry; actual depression below surrounding ground and rim. Not continuous shell, volume or support certification.',
        'threshold_status': 'published_pilot_pending_calibration'}


@_register('l2_terrain_relief', 'role grid_size min_coverage min_rms_m min_quadrant_rms_m required_quadrants')
def terrain_relief(check, evidence, spec):
    p = check.params; surface = np.concatenate([s for _, s in groups(evidence, p['role'])])
    center, radii, rotation = footprint(surface)
    # Cell-center observations cover the entire footprint; bottom faces and an
    # overall sloped but perfectly flat surface cannot produce artificial relief.
    axis = (np.arange(p['grid_size']) + .5) / p['grid_size'] * 2 - 1
    x, y = np.meshgrid(axis, axis); local = np.column_stack((x.ravel(), y.ravel()))
    xy = center + (local * radii) @ rotation.T
    z = VerticalSurface(surface).top(xy); global_z = scene_surface(evidence).top(xy)
    present = np.isfinite(z) & np.isfinite(global_z)
    finite = present & (np.abs(z - global_z) <= 1e-5)
    coverage = float(finite.mean())
    if coverage < p['min_coverage']:
        return 0., {'passed': False, 'coverage': coverage, 'geometric_coverage': float(present.mean()),
            'reason': 'Insufficient exposed terrain surface over its footprint; covered geometry cannot establish relief'}
    _, residual = plane(xy[finite], z[finite]); rms = float(np.sqrt(np.mean(residual ** 2)))
    quadrants = []
    for sx, sy in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        mask = (local[finite, 0] * sx > 0) & (local[finite, 1] * sy > 0)
        # Fit each region separately: a tilted plane or a single stepped slab
        # elsewhere does not certify local foreground/midground undulation.
        if mask.sum() < 3:
            value = 0.
        else:
            _, region = plane(xy[finite][mask], z[finite][mask])
            value = float(np.sqrt(np.mean(region ** 2)))
        quadrants.append(value)
    varied = sum(v >= p['min_quadrant_rms_m'] for v in quadrants)
    passed = rms >= p['min_rms_m'] and varied >= p['required_quadrants']
    return float(passed), {'passed': passed, 'coverage': coverage, 'plane_removed_rms_m': rms,
        'quadrant_plane_removed_rms_m': quadrants, 'varied_quadrants': varied,
        'query_count': len(xy), 'grid_size': p['grid_size'],
        'scope': 'Finite uniform samples of exposed terrain after local/global plane removal; not terrain style, ridges or crater semantics',
        'threshold_status': 'published_pilot_pending_calibration'}


def validate(check):
    p = check.params
    for key in ('role', 'support_role'):
        if key in p and (not isinstance(p[key], str) or not p[key]):
            raise ValueError('Nonempty geometry role required')
    def number(key, low, high, *, integer=False):
        value = p[key]
        if (type(value) not in ((int,) if integer else (int, float)) or not np.isfinite(value)
                or not low <= value <= high):
            raise ValueError('Invalid relief parameter: ' + key)
    if check.metric == 'l2_surface_depression':
        number('directions', 8, 128, integer=True); number('inner_fraction', .05, .5)
        number('outside_fraction', 1.01, 2); number('min_depth_m', 1e-5, 10)
        number('min_rim_height_m', 0, 10); number('required_fraction', .5, 1)
        number('occlusion_tolerance_m', 1e-7, .001)
        fractions = p['rim_fractions']
        if (not isinstance(fractions, list) or not 2 <= len(fractions) <= 16
                or any(type(f) not in (float, int) or not np.isfinite(f) or not .55 <= f <= .99 for f in fractions)
                or fractions != sorted(set(fractions))):
            raise ValueError('Sorted distinct rim sampling fractions required')
    elif check.metric == 'l2_terrain_relief':
        number('grid_size', 9, 129, integer=True); number('min_coverage', .8, 1)
        number('min_rms_m', 1e-5, 10); number('min_quadrant_rms_m', 1e-5, 10)
        number('required_quadrants', 1, 4, integer=True)
