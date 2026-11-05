"""Exact L2 triangle-distance predicate with an additional conservative AABB filter."""
import numpy as np
from src.evaluator.l2_triangle_contact import triangle_distances
from src.evaluator.metrics import MissingEvidence


def contact(left,right,tolerance,budget):
    delta=np.maximum(np.maximum(left.low-right.high,right.low-left.high),0)
    if np.linalg.norm(delta)>tolerance+1e-9:return False
    if len(left.xyz)>len(right.xyz):left,right=right,left
    if not hasattr(right,'_l3_triangle_bounds'):
        right._l3_triangle_bounds=(right.xyz.min(1),right.xyz.max(1))
    lows,highs=right._l3_triangle_bounds
    radius=right.radii.max()
    for triangle,center,own_radius in zip(left.xyz,left.centers,left.radii):
        ids=np.asarray(right.tree.query_ball_point(center,own_radius+radius+tolerance+1e-9),dtype=int)
        if not len(ids):continue
        gaps=np.maximum(np.maximum(lows[ids]-triangle.max(0),triangle.min(0)-highs[ids]),0)
        ids=ids[np.linalg.norm(gaps,axis=1)<=tolerance+1e-9]
        budget.pairs+=len(ids)
        if budget.pairs>budget.maximum:raise MissingEvidence('Exact triangle contact budget exceeded')
        for start in range(0,len(ids),4096):
            if np.any(triangle_distances(triangle,right.xyz[ids[start:start+4096]])<=tolerance+1e-9):return True
    return False
