"""Material connections across validated nested closed boundaries.

Containment is established only after complete boundary separation, a closed
manifold/orientation audit and a full winding query. Positive/negative nested
shells respectively add/subtract occupancy. No box or object-name shortcut.
"""
import numpy as np

from .l2_solid_geometry import improper_intersection, winding_classification
from .l2_support_chain import assemble, measure_chain, validate
from .metrics import MissingEvidence, _register


EPSILON = 1e-9


def closed_boundary(part, budget):
    """Validate the actual closed shell before interpreting its interior."""
    xyz = part.xyz
    if len(xyz) > 200_000:
        raise MissingEvidence('Material containment exceeds 200,000 triangles per boundary')
    vertices, inverse = np.unique(xyz.reshape(-1, 3), axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3)
    starts = faces.reshape(-1); ends = np.roll(faces, -1, axis=1).reshape(-1)
    edges = np.column_stack((np.minimum(starts, ends), np.maximum(starts, ends)))
    unique, ids, counts = np.unique(edges, axis=0, return_inverse=True, return_counts=True)
    orientations = np.bincount(ids, weights=np.where(starts < ends, 1, -1), minlength=len(unique))
    if not np.all(counts == 2):
        return None, {'valid': False, 'reason': 'open_or_nonmanifold_edges'}
    if np.any(orientations != 0):
        return None, {'valid': False, 'reason': 'inconsistent_boundary_orientation'}
    # A manifold vertex has a single cycle of incident opposite edges.
    neighbors = [[] for _ in vertices]
    for face in faces:
        for i in range(3):
            neighbors[face[i]].append((int(face[(i+1) % 3]), int(face[(i+2) % 3])))
    for links in neighbors:
        graph = {}
        for a, b in links:
            graph.setdefault(a, set()).add(b); graph.setdefault(b, set()).add(a)
        if not graph or any(len(v) != 2 for v in graph.values()):
            return None, {'valid': False, 'reason': 'nonmanifold_vertex_link'}
        reached = {next(iter(graph))}; stack = list(reached)
        while stack:
            for node in graph[stack.pop()] - reached:
                reached.add(node); stack.append(node)
        if len(reached) != len(graph):
            return None, {'valid': False, 'reason': 'disconnected_vertex_link'}
    low = xyz.min(axis=1); high = xyz.max(axis=1)
    radius = part.radii.max(); tested = 0
    for i, (center, own_radius) in enumerate(zip(part.centers, part.radii)):
        candidates = np.asarray(part.tree.query_ball_point(center, own_radius+radius+EPSILON), dtype=int)
        candidates = candidates[candidates > i]
        candidates = candidates[np.all(low[candidates] <= high[i]+EPSILON, axis=1)
                                & np.all(high[candidates] >= low[i]-EPSILON, axis=1)]
        budget.pairs += len(candidates); tested += len(candidates)
        if budget.pairs > budget.maximum:
            raise MissingEvidence('Contact measurement exceeds two million complete triangle pairs')
        for j in candidates:
            if improper_intersection(vertices, faces[i], faces[j], EPSILON):
                return None, {'valid': False, 'reason': 'self_intersection', 'triangle_pair': [i, int(j)]}
    centered = xyz-vertices.mean(axis=0)
    volume = float(np.einsum('ij,ij->i', centered[:, 0], np.cross(centered[:, 1], centered[:, 2])).sum()/6)
    if not np.isfinite(volume) or abs(volume) <= 1e-15:
        return None, {'valid': False, 'reason': 'zero_or_nonfinite_signed_volume'}
    return (vertices, faces, 1 if volume > 0 else -1), {
        'valid': True, 'signed_volume_m3': volume, 'self_intersection_pairs_tested': tested}


def material_assemble(surface, tolerance, budget):
    parts, detail = assemble(surface, tolerance, budget)
    detail = {**detail, 'material_method': 'validated_nested_signed_boundaries_v1',
              'material_edges': [], 'boundary_audits': {}, 'containment_parents': [], 'outside_winding': []}
    if detail['connected']:
        detail['material_status'] = 'surface_contacts_already_connect_all_parts'
        return parts, detail
    touch = {tuple(v) for v in detail['internal_contact_edges']}
    cache = {}; inside = [set() for _ in parts]
    def validated(i):
        if i not in cache:
            cache[i], detail['boundary_audits'][str(i)] = closed_boundary(parts[i], budget)
        return cache[i]
    for child, small in enumerate(parts):
        for parent, large in enumerate(parts):
            if child == parent or tuple(sorted((child, parent))) in touch:
                continue
            if np.any(small.low < large.low-EPSILON) or np.any(small.high > large.high+EPSILON):
                continue
            outer = validated(parent); inner = validated(child)
            if outer is None or inner is None:
                continue
            # assemble already proved all complete triangles of these boundaries
            # farther apart than the contact tolerance. For connected closed
            # boundaries, one non-boundary winding probe determines containment.
            point = small.xyz[0].mean(axis=0)
            state = int(winding_classification(outer[0], outer[1], point[None],
                                              tolerance=1e-5, epsilon_m=EPSILON)[0])
            if state < 0:
                raise MissingEvidence('Ambiguous closed-boundary material winding')
            if state == 1:
                inside[child].add(parent)
    parents = []
    for child, ancestors in enumerate(inside):
        nearest = [p for p in ancestors if not any(p in inside[q] for q in ancestors if q != p)]
        if len(nearest) > 1:
            raise MissingEvidence('Non-laminar nested material boundaries')
        parents.append(nearest[0] if nearest else None)
    links = list(touch); occupancy = []
    for child, parent in enumerate(parents):
        winding = 0; ancestor = parent; seen = {child}; root_sign = 1
        while ancestor is not None:
            if ancestor in seen:
                raise MissingEvidence('Cyclic material containment')
            seen.add(ancestor); root_sign = validated(ancestor)[2]
            winding += root_sign; ancestor = parents[ancestor]
        winding *= root_sign
        if parent is not None and (winding < 0 or winding+validated(child)[2]*root_sign < 0):
            raise MissingEvidence('Negative oriented material occupancy')
        occupancy.append(winding)
        # A cavity wall belongs to the material outside it. An isolated part
        # inside a zero-winding void does not gain a connection from enclosure.
        if parent is not None and winding != 0:
            links.append((child, parent)); detail['material_edges'].append([child, parent])
    reached = {0}
    while True:
        extended = reached | {b for a, b in links if a in reached} | {a for a, b in links if b in reached}
        if extended == reached:
            break
        reached = extended
    detail.update(connected=len(reached) == len(parts), containment_parents=parents,
                  outside_winding=occupancy, material_status='complete_boundaries_checked')
    return parts, detail


@_register('l2_material_support_chain', 'ground_role support_role rail_role vehicle_role minimum_supports contact_tolerance_m')
def material_support_chain(check, evidence, spec):
    score, detail = measure_chain(check, evidence, material_assemble)
    detail['scope'] = ('Full-surface contacts plus material connectivity from validated closed oriented nested boundaries. '
                       'Surface-connected open assemblies retain the earlier rule. '
                       'No strength, contact-area, semantic identity, general solid certification or acceptable-penetration verdict.')
    return score, detail
