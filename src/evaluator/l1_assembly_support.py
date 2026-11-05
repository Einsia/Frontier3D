"""L1 full-surface contact connectivity, reusing L2 triangle-contact machinery.

Isolated L1 objects have no required terrain. The largest actual connected
surface is the assembly datum. Report explicitly that this is connection, not
gravity stability, force balance, absence of intersections, or moving-joint proof.
"""
from pathlib import Path
import numpy as np
from orchestrator.tasks import sha256
from .l1_l2_alignment import digest
from .l2_physical import NearbyParts
from .l2_support_chain import ContactBudget, contact, pieces
from .metrics import MissingEvidence

METHOD = 'l1-assembly-support-v1'


def measure(plan, native):
    context = plan['physics']
    if context['method'] != METHOD or context['review_status'] != 'approved':
        raise ValueError('Frozen L1 assembly support context required')
    binding = {'method': METHOD, 'context_sha256': digest(context), 'scene_sha256': native['scene_sha256']}
    try:
        parts, identities, zero_area_objects = [], [], []
        for obj in native['objects']:
            path = Path(obj['path'])
            if sha256(path) != obj['sha256']:
                raise ValueError('Native geometry changed')
            with np.load(path, allow_pickle=False) as mesh:
                vertices, faces = mesh['vertices'], mesh['triangles']
                if (faces.ndim != 2 or faces.shape[1:] != (3,)
                        or faces.dtype.kind not in 'iu' or faces.size and
                        (faces.min()<0 or faces.max()>=len(vertices))):
                    raise MissingEvidence('Invalid candidate contact mesh triangle indices')
                xyz=vertices[faces]
                if not np.isfinite(xyz).all():raise MissingEvidence('Nonfinite contact geometry')
                twice_area=np.linalg.norm(np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]),axis=1)
                if len(twice_area) and np.all(twice_area==0):
                    # L2 already filters zero-area triangles from a combined
                    # surface. An all-zero Blender object has no area vote and
                    # must not create a contact bridge or invalidate its peers.
                    zero_area_objects.append({'object':obj['object'],'triangles':len(faces),'area_m2':0.})
                    continue
                for part in pieces(xyz, maximum_pieces=100000):
                    parts.append(part); identities.append(obj['object'])
        if not parts or len(parts)>100000:
            raise MissingEvidence('Empty or over-capacity connected piece population')
        lows, highs = np.asarray([p.low for p in parts]), np.asarray([p.high for p in parts])
        extent = highs.max(0)-lows.min(0)
        tolerance = float(extent.max()*context['policy']['relative_contact_tolerance'])
        areas = [float(np.linalg.norm(np.cross(p.xyz[:,1]-p.xyz[:,0],p.xyz[:,2]-p.xyz[:,0]),axis=1).sum()/2) for p in parts]
        root = int(np.argmax(areas))
        reached, frontier, links = {root}, [root], []
        nearby, budget = NearbyParts(lows, highs), ContactBudget(maximum=20_000_000)
        while frontier:
            i = frontier.pop()
            for j in nearby.query(i,tolerance):
                if j not in reached and contact(parts[i],parts[j],tolerance,budget):
                    reached.add(j); frontier.append(j); links.append([i,j])
        unsupported = [i for i in range(len(parts)) if i not in reached]
        return {**binding, 'status': 'measured', 'score': sum(areas[i] for i in reached)/sum(areas),
                'datum_piece': root, 'datum_object': identities[root], 'piece_count': len(parts),
                'supported_piece_count': len(reached), 'contact_tolerance_m': tolerance,
                'contact_edges': links, 'triangle_pairs_tested': budget.pairs,
                'zero_area_objects':zero_area_objects,
                'unsupported': [{'object': identities[i], 'piece': i, 'area_weight': areas[i]/sum(areas)} for i in unsupported],
                'scope': 'Surface-area fraction connected to the principal assembly at 0.5% overall-span contact tolerance; no floor requirement.',
                'limitations': context['limitations']}
    except MissingEvidence as error:
        return {**binding, 'status': 'not_measurable', 'score': None, 'reason': str(error)}
