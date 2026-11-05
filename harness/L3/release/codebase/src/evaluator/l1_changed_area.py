"""Conservative area of changed protected surface, not a sampled percentage.

Every actual triangle is classified or retained in the unresolved upper area.
Distance to a closed triangle union is 1-Lipschitz. A centroid distance minus
its triangle radius certifies changed area; a continuous distance upper bound
certifies unchanged area. Joint plane-domain enclosures can also certify the
protected portion of a boundary triangle. No fitted alignment is performed.
"""
from __future__ import annotations

import heapq
import math
import time

import numpy as np

from .l1_cylinder_area import frame, protected_domain_bounds
from .l1_patch_clearance import clearance_lower
from .l1_plane_area import triangle_area_bounds
from .l1_protected_surface import (
    near_planar_cover,
    split_polygon,
    triangulate,
)
from .l1_revolution import (
    EPSILON_M,
    convex_patch_neighbors,
    subdivide,
    triangle_to_mesh_upper,
)
from .l1_sections import _projected_radial_min
from .l1_surface import surface_distances

PROTOCOL = 'l1-changed-area-bounds-v1'


def _areas(triangles):
    return np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1)/2


def _domain(triangle, center_xy, radius, span):
    local = triangle[:, :2]-center_xy
    radii = np.linalg.norm(local, axis=1)
    # Convexity proves an entire triangle lies in the analytic cylinder.
    if (radii.max() < radius-EPSILON_M and triangle[:, 2].min() > span[0]+EPSILON_M
            and triangle[:, 2].max() < span[1]-EPSILON_M):
        return 'allowed'
    if (_projected_radial_min(list(local)) > radius+EPSILON_M
            or triangle[:, 2].max() < span[0]-EPSILON_M
            or triangle[:, 2].min() > span[1]+EPSILON_M):
        return 'protected'
    return 'boundary'


def _guided_split(triangle, target, tolerance):
    """Use measured distances only to choose cuts, NEVER to classify area.

    Isotropic midpoint splitting wastes effort along long zero-distance
    boundary edges. Cutting near the threshold can isolate their thin strip.
    Every resulting piece must still pass the full-surface bounds above.
    """
    center = triangle.mean(axis=0)
    distances = surface_distances(np.r_[triangle, center[None]], target)
    margin = max(8*EPSILON_M, tolerance*.01)
    levels = [value for value in (tolerance-margin, tolerance+margin)
              if distances[:3].min()+EPSILON_M < value < distances[:3].max()-EPSILON_M]
    if levels:
        gradient = np.linalg.lstsq(triangle[1:]-triangle[0], distances[1:3]-distances[0], rcond=None)[0]
        pieces = [triangle]
        for level in levels:
            offset = level-distances[0]+triangle[0] @ gradient
            split = []
            for polygon in pieces:
                inside, outside = split_polygon(polygon, gradient, offset)
                split.extend(part for part in (inside, outside) if len(part) >= 3)
            pieces = split
        children = np.asarray([face for polygon in pieces for face in triangulate(polygon)])
        if len(children) > 1 and np.isfinite(children).all():
            child_areas = _areas(children)
            area = _areas(triangle[None])[0]
            if np.all(child_areas > 0) and abs(child_areas.sum()-area) <= area*1e-10:
                return children, child_areas/child_areas.sum(), 'distance_level_cuts'
    if (distances[3] > distances[:3].max()+margin
            or distances[3] < distances[:3].min()-margin):
        children = np.asarray([[triangle[i], triangle[(i+1) % 3], center] for i in range(3)])
        return children, np.full(3, 1/3), 'centroid_fan'
    return subdivide(triangle[None]), np.full(4, .25), 'midpoint'


def changed_area(source, target, *, center_xy, radius, span, tolerance,
                 area_precision_m2=1e-8, max_patches=65536, max_depth=12, deadline=None):
    """Bound source area farther than tolerance from target outside edit zone.

`measured` means the interval is narrower than the requested area resolution;
it is NOT a preservation pass. Only an upper area of zero certifies unchanged
surface. An exhausted budget retains its valid interval as unavailable detail.
This floating-point guarded algorithm is not an exact-arithmetic CAD proof.
"""
    if (len(center_xy) != 2 or len(span) != 2
            or not np.isfinite([*center_xy, radius, *span, tolerance, area_precision_m2]).all()
            or radius <= 0 or span[0] >= span[1] or tolerance <= 32*EPSILON_M or area_precision_m2 <= 0
            or type(max_patches) is not int or not 1 <= max_patches <= 1048576
            or type(max_depth) is not int or not 0 <= max_depth <= 20
            or deadline is not None and (type(deadline) not in (float, int) or not math.isfinite(deadline))):
        raise ValueError('Invalid changed-area region, tolerance or budget')
    expired = deadline is not None and time.monotonic() >= deadline
    # Keep original source triangles. A prism subtraction can inflate a
    # thousand source faces into tens of thousands of artificial slivers.
    # The actual allowed cylinder is intersected in the source plane instead.
    clipped = source.xyz
    areas = _areas(clipped)
    region = {'center_xy': center_xy, 'radius': radius, 'span': span}
    domain_cache = {}
    initial_upper = areas.copy()
    for index, triangle in enumerate(clipped):
        if expired or deadline is not None and time.monotonic() >= deadline:
            break
        domain = _domain(triangle, np.asarray(center_xy), radius, span)
        if domain == 'allowed':
            initial_upper[index] = 0.
        elif domain == 'boundary':
            bounds = protected_domain_bounds(triangle, region, cache=domain_cache)
            if bounds is not None:
                initial_upper[index] = bounds[1]
    # Entries retain their complete-triangle lower/upper area bounds. Evaluate
    # all high-uncertainty leaves before refining already tight planar bounds.
    # Subdivision replaces a parent by a true partition; never count its
    # definite area again in its children.
    queue = [(-float(high), index, 0, triangle, float(area), 0., float(high), False, frame(triangle))
             for index, (area, high, triangle) in enumerate(zip(areas, initial_upper, clipped, strict=True)) if high > 0]
    heapq.heapify(queue)
    deferred = []
    initial_pass = True
    serial = len(clipped)
    lower = unchanged = allowed = 0.
    finished_lower = []
    stalled = []
    processed = planar_proofs = planar_area_bounds = 0
    split_counts = {'distance_level_cuts': 0, 'centroid_fan': 0, 'midpoint': 0}
    reason = None
    patches, planar_cache, area_cache, area_visits = None, {}, {}, {}
    boxes = (target.xyz.min(axis=1), target.xyz.max(axis=1)) if not expired else None

    def unresolved_area():
        return math.fsum([-row[0] for row in queue] + [-row[0] for row in deferred] + stalled)

    def definite_area():
        return math.fsum(finished_lower + [row[5] for row in queue] + [row[5] for row in deferred])

    best_lower, best_upper = 0., float(math.fsum(initial_upper))

    def retain_bounds():
        nonlocal best_lower, best_upper
        current_lower = definite_area()
        # Replacing a parent by yet-unmeasured children may temporarily lose
        # its tighter local bounds. The previously proved GLOBAL enclosure
        # stays valid for the same source surface; intersect, never discard it.
        best_lower = max(best_lower, current_lower)
        best_upper = min(best_upper, current_lower+unresolved_area())

    # Examine every remaining patch if no positive changed area has yet been
    # proved. This lets truly unchanged meshes reach an exact zero upper
    # bound instead of stopping early with an arbitrary small unknown tail.
    while queue or deferred:
        retain_bounds()
        if best_upper == 0 or best_lower > 0 and best_upper-best_lower <= area_precision_m2:
            break
        if deadline is not None and time.monotonic() >= deadline:
            reason = 'Changed-area deadline exhausted'
            break
        if processed >= max_patches:
            reason = 'Changed-area patch budget exhausted'
            break
        if not queue:
            # Finish one enclosure of every original source face before
            # spending the budget repeatedly subdividing one threshold strip.
            # Deferred parents still contribute their complete bounds above.
            queue, deferred = deferred, []
            heapq.heapify(queue)
            initial_pass = False
        batch = [heapq.heappop(queue) for _ in range(min(128, len(queue), max_patches-processed))]
        # Refinement of a previously bounded leaf does not rerun its expensive
        # plane overlay. Its children must independently prove their bounds.
        fresh = []
        for row in batch:
            _, _, depth, triangle, area, old_lower, old_upper, bounded, original_plane = row
            if not bounded:
                fresh.append(row)
                continue
            children, fractions, method = _guided_split(triangle, target, tolerance)
            split_counts[method] += 1
            for child, fraction in zip(children, fractions, strict=True):
                child_area = area*float(fraction)
                heapq.heappush(queue, (-child_area, serial, depth+1, child, child_area, 0., child_area, False, original_plane))
                serial += 1
        if not fresh:
            continue
        batch = fresh
        triangles = np.asarray([row[3] for row in batch])
        if patches is None:
            patches = convex_patch_neighbors(target)
        centers = triangles.mean(axis=1)
        sizes = np.linalg.norm(triangles-centers[:, None], axis=2).max(axis=1)
        upper = triangle_to_mesh_upper(triangles, target, patches)
        domains = [_domain(triangle, np.asarray(center_xy), radius, span) for triangle in triangles]
        uncertain = np.asarray([upper[i] >= tolerance-EPSILON_M and domain != 'allowed'
                                for i, domain in enumerate(domains)])
        distance = np.zeros(len(batch))
        if uncertain.any():
            distance[uncertain] = surface_distances(centers[uncertain], target)
            upper[uncertain] = np.minimum(upper[uncertain], distance[uncertain]+sizes[uncertain])
        processed += len(batch)
        for index, (_, _, depth, triangle, area, old_lower, old_upper, _, original_plane) in enumerate(batch):
            if deadline is not None and time.monotonic() >= deadline:
                # Retain the original bounds of every not-yet-visited member;
                # a batch is not permission for 128 further overlays after
                # one expensive union has consumed the remaining budget.
                for pending in batch[index:]:
                    heapq.heappush(queue, pending)
                reason = 'Changed-area deadline exhausted'
                break
            new_lower, new_upper = 0., area
            if domains[index] == 'allowed':
                allowed += area
                new_upper = 0.
            elif upper[index] < tolerance-EPSILON_M:
                unchanged += area
                new_upper = 0.
            elif domains[index] == 'protected' and distance[index]-sizes[index] > tolerance+EPSILON_M:
                new_lower = area
            elif near_planar_cover(triangle, target, tolerance, cache=planar_cache)[0]:
                unchanged += area
                planar_proofs += 1
                new_upper = 0.
            else:
                if distance[index]-sizes[index] > tolerance+EPSILON_M:
                    bounds = protected_domain_bounds(triangle, region, cache=domain_cache, plane_hint=original_plane)
                    enclosure = {'bounds_m2': bounds} if bounds is not None else None
                else:
                    enclosure = triangle_area_bounds(triangle, target, tolerance, boxes=boxes,
                        cache=area_cache, visits=area_visits,
                        allowed_region=region if domains[index] == 'boundary' else None, domain_cache=domain_cache,
                        plane_hint=original_plane)
                if enclosure is not None:
                    actual_area = float(_areas(triangle[None])[0])
                    # Parent area is preserved during partitioning. Apply the
                    # same area scale to the measured child enclosure.
                    if actual_area > 0:
                        lo, hi = np.asarray(enclosure['bounds_m2'])*area/actual_area
                        new_lower = float(lo)
                        new_upper = float(hi)
                        planar_area_bounds += 1
                elif domains[index] == 'protected' and clearance_lower(triangle, target, tolerance, boxes=boxes) > tolerance+EPSILON_M:
                    # Use costly pairwise separation only when the plane
                    # enclosure cannot resolve this face, not before every
                    # near-surface query that will need a plane overlay anyway.
                    new_lower = area
            width = max(0., new_upper-new_lower)
            if width:
                if depth >= max_depth:
                    stalled.append(width)
                    finished_lower.append(new_lower)
                else:
                    entry = (-width, serial, depth, triangle, area, new_lower, new_upper, True, original_plane)
                    if initial_pass:
                        deferred.append(entry)
                    else:
                        heapq.heappush(queue, entry)
                    serial += 1
            else:
                finished_lower.append(new_lower)
        if reason is not None:
            break
    retain_bounds()
    lower = best_lower
    uncertain_area = max(0., best_upper-best_lower)
    if reason is None and uncertain_area > area_precision_m2:
        reason = 'Changed-area depth limit reached'
    return {'protocol': PROTOCOL, 'status': 'measured' if reason is None else 'not_measurable',
            'reason': reason, 'hard_gate': False,
            'changed_area_m2_bounds': [max(0., float(lower)), max(0., float(lower+uncertain_area))],
            'unresolved_area_m2': float(uncertain_area), 'zero_change_certified': lower == 0 and uncertain_area == 0,
            'unchanged_area_m2': float(unchanged), 'allowed_area_discarded_m2': float(allowed),
            'protected_area_conservative_m2': float(math.fsum(initial_upper)),
            'area_precision_m2': area_precision_m2, 'surface_tolerance_m': tolerance,
            'processed_patches': processed, 'planar_union_proofs': planar_proofs, 'planar_area_bounds': planar_area_bounds,
            'split_counts': split_counts,
            'source_triangles': len(source.xyz), 'clipped_triangles': len(clipped),
            'clipping_performed': False, 'domain_enclosure_performed': not expired,
            'domain_policy': 'Original triangles intersected with inner/outer analytic cylinder plane enclosures',
            'refinement_policy': 'Enclose all original faces first; intersect all proved global bounds during refinement',
            'alignment': 'none; original world metres',
            'allowed_edit': {'center_xy_m': list(center_xy), 'radius_m': radius, 'span_m': list(span)},
            'scope': 'Directed surface area farther than tolerance; not a volume, semantic or topology verdict',
            'limitations': ['Floating-point guarded enclosure, not exact-arithmetic certification',
                           'Unresolved boundary/threshold area is retained, never assumed unchanged']}


def compare_changed_area(candidate, baseline, **parameters):
    """Keep candidate-added and baseline-removed surface areas separate."""
    deadline = parameters.get('deadline')
    forward_parameters = dict(parameters)
    if deadline is not None:
        now = time.monotonic()
        forward_parameters['deadline'] = min(deadline, now+max(0., deadline-now)/2)
    forward = changed_area(candidate, baseline, **forward_parameters)
    reverse = changed_area(baseline, candidate, **parameters)
    return {'protocol': PROTOCOL, 'hard_gate': False,
            'status': 'measured' if forward['status'] == reverse['status'] == 'measured' else 'not_measurable',
            'budget_policy': 'First direction receives at most half of remaining shared deadline; second uses the remainder',
            'candidate_to_baseline': forward, 'baseline_to_candidate': reverse,
            'scope': 'Two directed changed-surface areas; do not add them as one unique physical area'}
