"""Bound the complete distance between actual finite triangle surfaces.

No registration, random sampling, vertex-only pass or convex hull over holes.
Continuous upper bounds, actual point rejection witnesses, planar face unions
and longest-edge refinement share an explicit caller-owned deadline.
"""
from __future__ import annotations

import time

import numpy as np

from .l1_planar_tube import planar_tube_cover
from .l1_protected_surface import near_planar_cover
from .l1_revolution import EPSILON_M, convex_patch_neighbors, triangle_to_mesh_upper
from .l1_surface import surface_distances
from .l1_sweep import bisect_triangles


def directed_polyhedral(source, target, *, tolerance_m, approximation_m=0., deadline,
                        max_patches=262144, max_depth=24):
    if (any(type(v) not in (float, int) or not np.isfinite(v) for v in (tolerance_m, approximation_m, deadline))
            or approximation_m < 0 or tolerance_m-approximation_m <= 64*EPSILON_M
            or type(max_patches) is not int or max_patches <= 0
            or type(max_depth) is not int or not 0 <= max_depth <= 30):
        raise ValueError('Invalid continuous surface tolerance, approximation or budget')
    source = np.asarray(source, dtype=float)
    if source.ndim != 3 or source.shape[1:] != (3, 3) or not len(source) or not np.isfinite(source).all():
        raise ValueError('Expected nonempty finite source triangles')
    processed, upper_proved, lower_witness, union_proofs = 0, 0., 0., 0

    def report(status='not_measurable', **extra):
        return {'status': status, 'passed': status == 'passed', 'processed_patches': processed,
            'source_triangles': len(source), 'target_triangles': len(target.xyz),
            'continuous_upper_bound_m': upper_proved if status == 'passed' else None,
            'witness_lower_bound_m': lower_witness, 'planar_union_proofs': union_proofs,
            'approximation_m': approximation_m, 'tolerance_m': tolerance_m, **extra}

    if time.monotonic() >= deadline:
        return report(reason='Surface measurement deadline exhausted')
    patches, cache = convex_patch_neighbors(target), {}
    pending = source
    for depth in range(max_depth+1):
        unresolved = []
        for start in range(0, len(pending), 32):
            if time.monotonic() >= deadline:
                return report(reason='Surface measurement deadline exhausted')
            batch = pending[start:start+32]
            if processed+len(batch) > max_patches:
                return report(reason='Surface patch budget exhausted')
            processed += len(batch)
            upper = triangle_to_mesh_upper(batch, target, patches)+approximation_m
            # The sufficient planar proof is valid in any actual source plane,
            # not only one case's broad-face axis. Target holes remain holes.
            for index in np.flatnonzero(upper >= tolerance_m-EPSILON_M):
                if time.monotonic() >= deadline:
                    return report(reason='Planar cover deadline exhausted')
                triangle = batch[index]
                covered, _ = near_planar_cover(triangle, target, tolerance_m-approximation_m, cache=cache)
                if covered:
                    upper[index] = approximation_m+(tolerance_m-approximation_m-32*EPSILON_M)*np.sqrt(2)/3+EPSILON_M
                    union_proofs += 1
                else:
                    bound = planar_tube_cover(triangle, target, tolerance_m-approximation_m, cache=cache)
                    if bound is not None:
                        upper[index] = bound+approximation_m
                        union_proofs += 1
            accepted = upper < tolerance_m-EPSILON_M
            if accepted.any():
                upper_proved = max(upper_proved, float(upper[accepted].max()))
            if (~accepted).any():
                remaining = batch[~accepted]
                # Vertex/centroid samples are ONLY counterexample witnesses.
                # Passing always requires all complete source patches bounded.
                points = np.concatenate((remaining.reshape(-1, 3), remaining.mean(axis=1)))
                distances = surface_distances(points, target)
                lower_witness = max(lower_witness, max(0., float(distances.max())-approximation_m))
                if lower_witness > tolerance_m+EPSILON_M:
                    return report('failed', reason='Actual point-to-full-surface distance exceeds tolerance')
                centers = remaining.mean(axis=1)
                radii = np.linalg.norm(remaining-centers[:, None], axis=2).max(axis=1)
                lipschitz = surface_distances(centers, target)+radii+approximation_m
                small = lipschitz < tolerance_m-EPSILON_M
                if small.any():
                    upper_proved = max(upper_proved, float(lipschitz[small].max()))
                if (~small).any():
                    unresolved.append(remaining[~small])
        if time.monotonic() >= deadline:
            return report(reason='Surface result missed measurement deadline')
        if not unresolved:
            return report('passed', depth=depth)
        pending = np.concatenate(unresolved)
        if depth >= max_depth or processed+2*len(pending) > max_patches:
            return report(reason='Unresolved surface patches at subdivision/depth limit')
        pending = bisect_triangles(pending)
    raise AssertionError('Unreachable refinement state')


def compare_polyhedral(candidate, reference, *, tolerance_m, approximation_m=0., deadline,
                       max_patches=262144, max_depth=24):
    now = time.monotonic()
    forward = directed_polyhedral(candidate.xyz, reference, tolerance_m=tolerance_m,
        approximation_m=approximation_m, deadline=now+max(0., deadline-now)/2,
        max_patches=max_patches, max_depth=max_depth)
    reverse = directed_polyhedral(reference.xyz, candidate, tolerance_m=tolerance_m,
        approximation_m=approximation_m, deadline=deadline, max_patches=max_patches, max_depth=max_depth)
    statuses = {forward['status'], reverse['status']}
    status = 'failed' if 'failed' in statuses else 'passed' if statuses == {'passed'} else 'not_measurable'
    return {'protocol': 'l1-polyhedral-continuous-bounds-v1', 'status': status, 'passed': status == 'passed',
        'candidate_to_reference': forward, 'reference_to_candidate': reverse,
        'alignment': 'None; fixed world coordinates', 'tolerance_m': tolerance_m,
        'approximation_m': approximation_m, 'numeric_guard_m': EPSILON_M,
        'scope': 'Complete finite surfaces only, not topology, occupancy or task completion'}
