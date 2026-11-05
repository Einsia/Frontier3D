"""Complete projected-triangle disjointness, with exact ambiguous predicates.

Boundary contact is allowed; any positive-area intersection is rejected. This
checks actual selected surfaces, including concavities and holes, not their hull.
"""
from fractions import Fraction

import numpy as np
from scipy.spatial import cKDTree

from .l2_reference_numeric import groups
from .metrics import MissingEvidence, _register


def orientation(a, b, points):
    """Signs of 2D determinants, exact for the supplied binary64 coordinates."""
    a, b, points = np.broadcast_arrays(a, b, points)
    u = b-a; v = points-a
    left = u[..., 0]*v[..., 1]; right = u[..., 1]*v[..., 0]
    determinant = left-right
    uncertain = np.abs(determinant) <= 16*np.finfo(float).eps*(np.abs(left)+np.abs(right))
    signs = np.asarray(np.sign(determinant), dtype=np.int8)
    flat = signs.reshape(-1)
    for index in np.flatnonzero(uncertain):
        x, y, z = [row.reshape(-1, 2)[index] for row in (a, b, points)]
        # Fraction(float) preserves the input bit pattern, not rounded decimals.
        ax, ay, bx, by, px, py = map(Fraction, map(float, (*x, *y, *z)))
        value = (bx-ax)*(py-ay)-(by-ay)*(px-ax)
        flat[index] = (value > 0)-(value < 0)
    return signs


def projected(surface):
    surface = np.asarray(surface, dtype=float)
    if (surface.ndim != 3 or surface.shape[1:] != (3, 3) or not len(surface)
            or not np.isfinite(surface).all() or np.abs(surface).max() > 1e8):
        raise MissingEvidence('Finite complete world triangles within +/-100 million metres required')
    if len(surface) > 1_000_000:
        raise MissingEvidence('Projected separation exceeds one million triangles per role')
    xy = surface[:, :, :2].copy()
    # Canonicalization removes exact duplicate projections, including top/bottom
    # faces. It never fills a hole or merges approximately coincident vertices.
    order = np.lexsort((xy[:, :, 1], xy[:, :, 0]), axis=1)
    xy = np.take_along_axis(xy, order[:, :, None], axis=1)
    xy = np.unique(xy.reshape(-1, 6), axis=0).reshape(-1, 3, 2)
    sign = orientation(xy[:, 0], xy[:, 1], xy[:, 2])
    xy = xy[sign != 0]; sign = sign[sign != 0]
    if not len(xy):
        raise MissingEvidence('Nonzero projected surface area required')
    xy[sign < 0] = xy[sign < 0][:, [0, 2, 1]]
    return xy


def interior_intersections(first, others):
    """Strict SAT for CCW triangles; intersections of edges alone do not pass."""
    alive = np.ones(len(others), dtype=bool)
    for i in range(3):
        alive &= np.any(orientation(first[i], first[(i+1) % 3], others) > 0, axis=1)
        alive &= np.any(orientation(others[:, i, None], others[:, (i+1) % 3, None], first) > 0, axis=1)
    return alive


class ProjectionIndex:
    def __init__(self, surface):
        self.triangles = projected(surface)
        self.low = self.triangles.min(axis=1); self.high = self.triangles.max(axis=1)
        self.centers = self.triangles.mean(axis=1)
        self.radii = np.linalg.norm(self.triangles-self.centers[:, None], axis=2).max(axis=1)
        self.tree = cKDTree(self.centers)
        self.rounding_margin = 64*np.finfo(float).eps*max(1., float(np.abs(self.triangles).max()))

    def intersects(self, other, budget):
        """Only a complete pair predicate can return an overlap witness."""
        margin = self.rounding_margin+other.rounding_margin
        for index, (tri, center, radius) in enumerate(zip(self.triangles, self.centers, self.radii)):
            ids = np.asarray(other.tree.query_ball_point(center, radius+other.radii.max()+margin), dtype=int)
            ids = ids[np.all(other.high[ids] > self.low[index], axis=1)
                      & np.all(other.low[ids] < self.high[index], axis=1)]
            budget['pairs'] += len(ids)
            if budget['pairs'] > budget['maximum']:
                raise MissingEvidence('Projected separation exceeds two million candidate triangle pairs')
            for start in range(0, len(ids), 4096):
                batch = ids[start:start+4096]
                found = np.flatnonzero(interior_intersections(tri, other.triangles[batch]))
                if len(found):
                    j = int(batch[found[0]])
                    return {'selected_triangle_xy': tri.tolist(), 'excluded_triangle_xy': other.triangles[j].tolist()}
        return None


def validate(check):
    p = check.params
    if (set(p) != {'role', 'excluded_role'} or any(not isinstance(v, str) or not v for v in p.values())
            or p['role'] == p['excluded_role']):
        raise ValueError('Distinct selected and excluded projection roles required')


@_register('l2_projected_disjoint', 'role excluded_role')
def projected_disjoint(check, evidence, spec):
    p = check.params; selected = groups(evidence, p['role']); excluded = groups(evidence, p['excluded_role'])
    if len(selected) > 128 or len(excluded) > 128:
        raise MissingEvidence('Projected separation exceeds 128 entities per role')
    if sum(len(s) for _, s in selected) > 1_000_000 or sum(len(s) for _, s in excluded) > 1_000_000:
        raise MissingEvidence('Projected separation exceeds one million triangles per role')
    obstacle = ProjectionIndex(np.concatenate([s for _, s in excluded]))
    budget = {'pairs': 0, 'maximum': 2_000_000}; rows = []
    for entity, surface in selected:
        index = ProjectionIndex(surface); witness = index.intersects(obstacle, budget)
        rows.append({'entity': entity['id'], 'passed': witness is None,
                     'projected_triangles': len(index.triangles), 'overlap_witness': witness})
    return float(all(r['passed'] for r in rows)), {
        'entities': rows, 'complete_candidate_pairs': budget['pairs'],
        'boundary_rule': 'Zero-area boundary contact allowed; every positive-area overlap rejected',
        'arithmetic': 'Float64 filter with exact binary-coordinate determinant fallback',
        'scope': 'Complete selected XY surface projections; not semantic identity, 3D penetration, clearance or hidden ground inference'}
