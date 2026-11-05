"""Full-surface contact chains, separate from strength and penetration verdicts.

World-space triangles define connected pieces and pairwise Euclidean proximity.
Names, bounds, diagnostic support points and authored part tags are not answers.
"""
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from .l2_reference_numeric import groups
from .l2_triangle_contact import triangle_distances
from .metrics import MissingEvidence, _register


class Surface:
    def __init__(self, triangles):
        area = np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)
        triangles = triangles[area > 1e-14]
        if not len(triangles):
            raise MissingEvidence('Nondegenerate complete contact geometry required')
        self.xyz = triangles
        self.low = triangles.min((0, 1)); self.high = triangles.max((0, 1))
        self.centers = triangles.mean(axis=1)
        self.radii = np.linalg.norm(triangles-self.centers[:, None], axis=2).max(axis=1)
        self._tree = None

    @property
    def tree(self):
        if self._tree is None:
            self._tree = cKDTree(self.centers)
        return self._tree


class ContactBudget:
    def __init__(self, maximum=2_000_000):
        self.maximum = maximum
        self.pairs = 0


def contact(left, right, tolerance, budget):
    """Conservative complete broad phase, then triangle feature distances."""
    delta = np.maximum(np.maximum(left.low-right.high, right.low-left.high), 0)
    if np.linalg.norm(delta) > tolerance+1e-9:
        return False
    if len(left.xyz) > len(right.xyz):
        left, right = right, left
    radius = right.radii.max()
    for triangle, center, own_radius in zip(left.xyz, left.centers, left.radii):
        candidates = right.tree.query_ball_point(center, own_radius+radius+tolerance+1e-9)
        ids = np.asarray(candidates, dtype=int)
        if not len(ids):
            continue
        ids = ids[np.linalg.norm(right.centers[ids]-center, axis=1) <= own_radius+right.radii[ids]+tolerance+1e-9]
        budget.pairs += len(ids)
        if budget.pairs > budget.maximum:
            raise MissingEvidence(f'Contact measurement exceeds {budget.maximum} complete triangle pairs')
        for start in range(0, len(ids), 4096):
            if np.any(triangle_distances(triangle, right.xyz[ids[start:start+4096]]) <= tolerance+1e-9):
                return True
    return False


def pieces(surface, *, maximum_pieces=128, maximum_triangles=1_000_000):
    """Split using actual shared coordinates, independent of Blender objects."""
    if len(surface) > maximum_triangles:
        raise MissingEvidence(f'Contact measurement exceeds {maximum_triangles} complete triangles')
    area = np.linalg.norm(np.cross(surface[:, 1]-surface[:, 0], surface[:, 2]-surface[:, 0]), axis=1)
    surface = surface[area > 1e-14]
    if not len(surface):
        raise MissingEvidence('Nondegenerate complete contact geometry required')
    vertices, inverse = np.unique(surface.reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    a = faces.reshape(-1); b = np.roll(faces, -1, axis=1).reshape(-1)
    graph = coo_matrix((np.ones(len(a), dtype=bool), (a, b)), shape=(len(vertices), len(vertices))).tocsr()
    count, labels = connected_components(graph, directed=False)
    if count > maximum_pieces:
        raise MissingEvidence(f'Contact entity exceeds {maximum_pieces} disconnected surface pieces')
    # Linear-size split after sorting; avoids scanning all triangles once per
    # piece for joined fibers, rubble, tiled terrain and other large assemblies.
    ids=labels[faces[:,0]]
    order=np.argsort(ids,kind='stable')
    cuts=np.flatnonzero(np.diff(ids[order]))+1
    return [Surface(surface[index]) for index in np.split(order,cuts)]


def assemble(surface, tolerance, budget):
    parts = pieces(surface)
    links = []
    reached = {0}
    # Components may be separate touching objects, welded meshes or joined meshes.
    for i, first in enumerate(parts):
        for j in range(i+1, len(parts)):
            if contact(first, parts[j], tolerance, budget):
                links.append((i, j))
    while True:
        extended = reached | {b for a, b in links if a in reached} | {a for a, b in links if b in reached}
        if extended == reached:
            break
        reached = extended
    vertices = surface.reshape(-1, 3)
    non_coplanar = bool(np.linalg.matrix_rank(vertices-vertices.mean(axis=0), tol=1e-7) == 3)
    return parts, {'piece_count': len(parts), 'internal_contact_edges': [list(v) for v in links],
                   'connected': len(reached) == len(parts), 'non_coplanar': non_coplanar}


@_register('l2_support_chain', 'ground_role support_role rail_role vehicle_role minimum_supports contact_tolerance_m')
def support_chain(check, evidence, spec):
    return measure_chain(check, evidence, assemble)


def measure_chain(check, evidence, assembler):
    p = check.params; tolerance = p['contact_tolerance_m']; budget = ContactBudget()
    selected = {key: groups(evidence, p[key]) for key in ('ground_role', 'support_role', 'rail_role', 'vehicle_role')}
    if any(len(values) > 128 for values in selected.values()):
        raise MissingEvidence('Contact selection exceeds 128 entities per role')
    # An entity cannot claim several nodes of its own support chain.
    member_sets = {key: {name for entity, _ in values for name, _ in entity['members']} for key, values in selected.items()}
    keys = list(selected)
    if any(member_sets[a] & member_sets[b] for i, a in enumerate(keys) for b in keys[i+1:]):
        raise MissingEvidence('Distinct actual geometry required for support-chain roles')
    ground = Surface(np.concatenate([surface for _, surface in selected['ground_role']]))
    rail_surface = np.concatenate([surface for _, surface in selected['rail_role']])
    _, rail = assembler(rail_surface, tolerance, budget)
    rail_index = Surface(rail_surface)
    supports = []; signatures = set()
    for entity, surface in selected['support_role']:
        _, detail = assembler(surface, tolerance, budget)
        index = Surface(surface)
        # Exact coincident bounds are not six spatially distinct supports. This
        # narrow duplicate guard is public; semantic instance identity is deferred.
        signature = tuple(np.round(np.r_[index.low, index.high], 6))
        duplicate = signature in signatures; signatures.add(signature)
        grounded = contact(index, ground, tolerance, budget)
        attached = contact(index, rail_index, tolerance, budget)
        supports.append({'entity': entity['id'], **detail, 'ground_contact': grounded,
                         'rail_contact': attached, 'duplicate_bounds': duplicate,
                         'passed': detail['connected'] and detail['non_coplanar'] and grounded and attached and not duplicate})
    vehicles = []
    for entity, surface in selected['vehicle_role']:
        _, detail = assembler(surface, tolerance, budget)
        attached = contact(Surface(surface), rail_index, tolerance, budget)
        vehicles.append({'entity': entity['id'], **detail, 'rail_contact': attached,
                         'passed': detail['connected'] and detail['non_coplanar'] and attached})
    result = bool(rail['connected'] and rail['non_coplanar'] and len(supports) >= p['minimum_supports']
                  and all(row['passed'] for row in supports+vehicles))
    return float(result), {'rail': rail, 'supports': supports, 'vehicles': vehicles,
                          'complete_triangle_pairs_tested': budget.pairs, 'contact_tolerance_m': tolerance,
                          'threshold_status': 'published_pilot_pending_calibration',
                          'scope': 'Complete-surface proximity and internal component connectivity; contact can be lateral, above or below. '
                                   'No load-bearing, contact-area, semantic part identity, watertightness or non-design penetration certification.'}


def validate(check):
    p = check.params
    roles = [p[key] for key in ('ground_role', 'support_role', 'rail_role', 'vehicle_role')]
    if any(not isinstance(v, str) or not v for v in roles) or len(set(roles)) != 4:
        raise ValueError('Four distinct nonempty support-chain roles required')
    if type(p['minimum_supports']) is not int or not 1 <= p['minimum_supports'] <= 128:
        raise ValueError('Support count must be 1..128')
    v = p['contact_tolerance_m']
    if type(v) not in (int, float) or not np.isfinite(v) or not 0 <= v <= .05:
        raise ValueError('Finite support contact tolerance must be 0..0.05 m')
