"""Static support plausibility on complete evaluated geometry, shared by L2.

No object name, parent, role, or bounding-box overlap proves contact. This first
version measures connection to terrain, including wall/ceiling attachments; it
does not certify force balance, penetration depth, friction, or navigability.
"""
import numpy as np
from scipy.spatial import cKDTree

from .l2_reference_numeric import triangles
from .l2_support_chain import ContactBudget, contact, pieces
from .metrics import MissingEvidence

METHOD = 'static-support-v1'
DEFAULT_POLICY = {'method': METHOD, 'gravity': 'down_z', 'ground_mode': 'scene', 'contact_tolerance_m': .02,
                  'ground_lower_fraction': .35, 'minimum_ground_area_fraction': .15}

SURFACE_TYPES = frozenset({'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'})


def visible_surfaces(objects):
    """Native curves count through their evaluated surfaces, never their labels.

    A measured curve with no faces has no renderable solid surface. Missing
    measurement is different: retain it so triangle loading fails explicitly.
    """
    return {name:obj for name,obj in objects.items()
            if obj.get('type') in SURFACE_TYPES and obj.get('visible_render')
            and not (obj.get('type') != 'MESH' and obj.get('evaluated_surface_status') == 'empty'
                     and obj.get('polygon_count') == 0 and not obj.get('surface_triangles'))}


class NearbyParts:
    """Complete broad phase with size buckets; tiny fibers need no N² scan."""
    def __init__(self, lows, highs):
        self.lows, self.highs = lows, highs
        centers=(lows+highs)/2
        radii=np.linalg.norm(highs-lows,axis=1)/2
        self.centers,self.radii=centers,radii
        buckets=np.ceil(np.log2(np.maximum(radii,1e-12))).astype(int)
        self.groups=[]
        for bucket in np.unique(buckets):
            ids=np.flatnonzero(buckets==bucket)
            self.groups.append((ids,cKDTree(centers[ids]),float(radii[ids].max())))

    def query(self,index,tolerance):
        found=[]
        for ids,tree,radius in self.groups:
            positions=tree.query_ball_point(self.centers[index],self.radii[index]+radius+tolerance+1e-9)
            selected=ids[np.asarray(positions,dtype=int)]
            near=(np.all(self.lows[selected]<=self.highs[index]+tolerance+1e-9,axis=1)
                  & np.all(self.highs[selected]>=self.lows[index]-tolerance-1e-9,axis=1))
            found.extend(selected[near].tolist())
        return sorted(found)


def validate_policy(policy):
    expected = {**DEFAULT_POLICY, 'gravity': policy.get('gravity'), 'ground_mode': policy.get('ground_mode')}
    if (policy != expected or policy['gravity'] not in {'down_z', 'space'}
            or policy['ground_mode'] not in {'scene','diorama_platform'}):
        raise ValueError('Unsupported version-bound physical plausibility policy')


def physical_plausibility(evidence, policy):
    validate_policy(policy)
    if policy['gravity'] == 'space':
        return {'method': METHOD, 'status': 'not_applicable', 'score': 1.,
                'reason': 'Reference describes outer space; gravitational grounding is inapplicable.',
                'exception_source': 'frozen evaluator task policy', 'measured_coverage': None}
    try:
        return _measure(evidence, policy)
    except MissingEvidence as exc:
        return {'method': METHOD, 'status': 'not_measurable', 'score': 0.,
                'reason': str(exc), 'measured_coverage': 0., 'affects_validity': False}


def _measure(evidence, policy):
    objects = evidence.get('scene', {}).get('objects', {})
    parts, identities = [], []
    for name, obj in sorted(visible_surfaces(objects).items()):
        for index, part in enumerate(pieces(triangles(obj, evidence),maximum_pieces=100000)):
            parts.append(part)
            identities.append({'object': name, 'piece': index})
    if not parts:
        raise MissingEvidence('No visible complete mesh geometry for support measurement')
    if len(parts) > 100000:
        raise MissingEvidence('Support analysis exceeds 100000 connected pieces')
    excluded=[]
    if policy['ground_mode']=='diorama_platform' and len(parts)>1:
        # Reviewed diorama tasks may have a detached studio shadow-catching
        # slab far larger than the actual terrain. It is presentation geometry,
        # not the support datum of the city/island. Require complete disconnection
        # as well as a low thin shape and at least 4x the next actual footprint.
        footprint=np.array([np.prod((p.high-p.low)[:2]) for p in parts])
        order=np.argsort(footprint);index=int(order[-1]);part=parts[index]
        extent=part.high-part.low
        all_low=min(p.low[2] for p in parts);all_high=max(p.high[2] for p in parts)
        isolated=False
        if (footprint[index]>=4*max(footprint[order[-2]],1e-12)
                and extent[2]<=.01*max(extent[:2]) and part.high[2]<=all_low+.1*(all_high-all_low)):
            budget=ContactBudget(maximum=20_000_000)
            isolated=not any(contact(part,p,policy['contact_tolerance_m'],budget)
                             for i,p in enumerate(parts) if i!=index)
        if isolated:
            excluded=[{**identities[index],'reason':'Detached oversized diorama presentation slab',
                       'bounds':[part.low.tolist(),part.high.tolist()]}]
            parts.pop(index);identities.pop(index)
    lows = np.asarray([p.low for p in parts]); highs = np.asarray([p.high for p in parts])
    low, high = lows.min(0), highs.max(0)
    extent = high-low
    tolerance = policy['contact_tolerance_m']
    ground_layers = {}
    areas = []
    low_projected_area=0.
    for index, part in enumerate(parts):
        cross = np.cross(part.xyz[:, 1]-part.xyz[:, 0], part.xyz[:, 2]-part.xyz[:, 0])
        area = np.linalg.norm(cross, axis=1)/2
        areas.append(float(area.sum()))
        low_projected_area+=float(np.abs(cross[part.centers[:,2]<=low[2]+policy['ground_lower_fraction']*extent[2],2]).sum()/2)
        # Aggregate actual coplanar triangle areas across objects. Many thin
        # wooden planks can form a floor without any one plank being broad.
        # Distant background mountains must not inflate an XY-box denominator.
        horizontal = (np.abs(cross[:, 2]) >= .98*np.linalg.norm(cross, axis=1))
        horizontal &= part.centers[:, 2] <= low[2]+policy['ground_lower_fraction']*extent[2]
        # Quantized height bins avoid summing every shelf of a tall assembly.
        for bucket in np.unique(np.floor(part.centers[horizontal, 2]/tolerance)):
            selected = horizontal & (np.floor(part.centers[:, 2]/tolerance) == bucket)
            projected_area = float(np.abs(cross[selected, 2]).sum()/2)
            z = float(np.average(part.centers[selected, 2], weights=area[selected]))
            # A low thin surface or a relatively broad solid base may anchor
            # the scene. Small upright furniture parts do not become terrain.
            dimensions=part.high-part.low
            ground_layers.setdefault(float(bucket),[]).append((projected_area,z,index,
                bool(dimensions[2] <= .25*max(dimensions[:2]))))
    total_horizontal=sum(sum(v[0] for v in layer) for layer in ground_layers.values())
    candidates=[]
    for bucket, layer in ground_layers.items():
        area=sum(v[0] for v in layer)
        terrain=[v for v in layer if v[3] or v[0]>=policy['minimum_ground_area_fraction']*total_horizontal]
        terrain_area=sum(v[0] for v in terrain)
        if terrain and terrain_area>=policy['minimum_ground_area_fraction']*total_horizontal:
            z=sum(v[0]*v[1] for v in terrain)/terrain_area
            candidates.append((terrain_area,z,terrain))
    ground_inference='horizontal_layer'
    if not candidates:
        # Rough terrain need not fit a 2 cm coplanar bin. A fallback datum must
        # be one broad, low, thin connected surface with actual projected area.
        rough=[]
        cutoff=low[2]+policy['ground_lower_fraction']*extent[2]
        for index,part in enumerate(parts):
            dimensions=part.high-part.low
            if part.high[2]>cutoff or dimensions[2]>.25*max(dimensions[:2]):continue
            cross=np.cross(part.xyz[:,1]-part.xyz[:,0],part.xyz[:,2]-part.xyz[:,0])
            projected=float(np.abs(cross[:,2]).sum()/2)
            if projected>1e-12 and projected>=policy['minimum_ground_area_fraction']*low_projected_area:
                rough.append((projected,float(part.high[2]),[(projected,float(part.high[2]),index,True)]))
        if not rough:
            raise MissingEvidence('No broad low terrain layer; grounding requires a reviewed task datum')
        candidates=rough;ground_inference='low_connected_terrain'
    # Largest actual layer wins; choose its upper surface when areas tie.
    _,ground_z,terrain=max(candidates,key=lambda v:(v[0],v[1]))
    roots={v[2] for v in terrain}
    nearby=NearbyParts(lows,highs)
    reached = set(roots); frontier = sorted(roots); links = []
    budget = ContactBudget(maximum=20_000_000)
    while frontier:
        i = frontier.pop(0)
        for j in nearby.query(i,tolerance):
            j = int(j)
            if j in reached:
                continue
            if contact(parts[i], parts[j], tolerance, budget):
                reached.add(j); frontier.append(j); links.append([i, j])
    # Surface-area weights resist changing object names or splitting one mesh
    # into many objects. Terrain roots do not dilute the floating-object penalty.
    scored = [i for i in range(len(parts)) if i not in roots]
    denominator = sum(areas[i] for i in scored)
    if denominator <= 0:
        raise MissingEvidence('Terrain alone has no supported subject geometry to measure')
    unsupported = [i for i in scored if i not in reached]
    score = sum(areas[i] for i in scored if i in reached)/denominator
    return {'method': METHOD, 'status': 'measured', 'score': score, 'measured_coverage': 1.,
            'ground_mode':policy['ground_mode'],'excluded_presentation_geometry':excluded,
            'ground_inference':ground_inference,
            'affects_validity': False, 'contact_tolerance_m': tolerance, 'ground_height_m': ground_z,
            'ground_roots': [{**identities[i], 'index': i} for i in sorted(roots)],
            'piece_count': len(parts), 'supported_piece_count': len(reached),
            'unsupported_piece_count': len(unsupported), 'contact_edges': links,
            'complete_triangle_pairs_tested': budget.pairs,
            'unsupported_surface_fraction': 1.-score,
            'unsupported': [{**identities[i], 'surface_area_m2': areas[i],
                             'score_weight': areas[i]/denominator,
                             'bounds': [parts[i].low.tolist(), parts[i].high.tolist()]} for i in unsupported],
            'scope': 'Complete-surface connection to inferred ground; lateral and overhead attachment allowed.',
            'limitations': ['Contact is a static plausibility proxy, not load-bearing certification.',
                            'Deep penetration, solid containment, balance, friction and dynamics are not scored.',
                            'Ground inference is geometric and requires review for unusual terrain.']}
