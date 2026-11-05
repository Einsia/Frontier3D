"""L2 task-context adaptations: edited geometry, existing fixtures and sky bodies."""
import copy
import numpy as np

from .l2_physical import DEFAULT_POLICY, SURFACE_TYPES, physical_plausibility, validate_policy, visible_surfaces
from .l2_reference_numeric import triangles
from .l2_support_chain import Surface, ContactBudget, contact, pieces
from .metrics import MissingEvidence

VERSION='physical-context-v1'
SKY_TASK='L2/Brief2Scene/task_L2_Brief2Scene_009'


def configuration(category,task_id,edit_mode=None):
    if category=='SceneEdit':
        return {'version':VERSION,'scope':'edit_delta','edit_mode':edit_mode,'contact_tolerance_m':.02}
    diorama=category=='Brief2Scene' and task_id[-3:] in {'001','002','003','004','005','006','007','010'}
    return {'version':VERSION,'scope':'scene','policy':{**DEFAULT_POLICY,
            'ground_mode':'diorama_platform' if diorama else 'scene'},'sky_sphere_exception':task_id==SKY_TASK}


def validate_configuration(config,category,task_id,edit_mode=None):
    if config!=configuration(category,task_id,edit_mode):
        raise ValueError('Physical context must match the versioned task adaptation')
    if config['scope']=='scene':validate_policy(config['policy'])
    elif edit_mode not in {'geometry','lighting'}:raise ValueError('Explicit physical edit mode required')


def stable_geometry(before,after):
    if not after or before.get('type') not in SURFACE_TYPES or after.get('type')!=before.get('type'):return False
    if before.get('visible_render')!=after.get('visible_render'):return False
    # Independently collected, complete evaluated world-space hashes, not names
    # or candidate-declared parent/role/"physics exempt" flags.
    for key in ('surface_order_independent_sha256','evaluated_geometry_sha256'):
        if before.get(key) and before[key]==after.get(key):return True
    return False


def edit_support(evidence,config):
    before=evidence.get('baseline',{}).get('objects',{})
    after=evidence.get('scene',{}).get('objects',{})
    original=visible_surfaces(before)
    candidate=visible_surfaces(after)
    # Unmeasured native surfaces must not silently become unchanged fixtures.
    for obj in [*original.values(),*candidate.values()]:
        if obj.get('type')!='MESH' and not obj.get('evaluated_geometry_sha256'):
            raise MissingEvidence('Complete independently evaluated native surface required')
    if not original:raise MissingEvidence('Independent initial-scene geometry required for edit physics')
    anchors={n:o for n,o in candidate.items() if n in original and stable_geometry(original[n],o)}
    changed={n:o for n,o in candidate.items() if n not in anchors}
    retention=len(anchors)/len(original)
    if config['edit_mode']=='lighting':
        retention=len(anchors)/max(len(set(original)|set(candidate)),1)
    if not changed:
        return {'method':VERSION,'status':'measured','score':retention if config['edit_mode']=='lighting' else 0.,
            'scope':'Preservation of supplied geometry for light-only edits; added-part support for geometry edits',
            'geometry_preservation':retention,'added_or_changed_meshes':0,'affects_validity':False,
            'reason':'No changed geometry; lighting preserves supplied support, but missing geometry targets earn no support credit.'}
    parts=[];identities=[]
    for name,obj in sorted(changed.items()):
        for index,part in enumerate(pieces(triangles(obj,evidence),maximum_pieces=15000)):
            parts.append(part);identities.append({'object':name,'piece':index})
    if len(parts)>15000:raise MissingEvidence('Edited geometry exceeds 15000 complete pieces')
    tolerance=config['contact_tolerance_m'];budget=ContactBudget(maximum=20_000_000)
    cache={};reached=set();attachments=[]
    for i,part in enumerate(parts):
        for name,obj in sorted(anchors.items()):
            bounds=np.asarray(obj.get('bounds',[]),float)
            if bounds.shape!=(2,3) or not np.isfinite(bounds).all():
                raise MissingEvidence('Finite independently measured anchor bounds required')
            if np.any(bounds[0]>part.high+tolerance) or np.any(bounds[1]<part.low-tolerance):continue
            if name not in cache:cache[name]=Surface(triangles(obj,evidence))
            if contact(part,cache[name],tolerance,budget):
                reached.add(i);attachments.append({'piece':i,'initial_scene_anchor':name});break
    lows=np.asarray([p.low for p in parts]);highs=np.asarray([p.high for p in parts])
    frontier=list(reached);links=[]
    while frontier:
        i=frontier.pop(0)
        nearby=np.all(lows<=highs[i]+tolerance,axis=1)&np.all(highs>=lows[i]-tolerance,axis=1)
        for j in np.flatnonzero(nearby):
            j=int(j)
            if j not in reached and contact(parts[i],parts[j],tolerance,budget):
                reached.add(j);frontier.append(j);links.append([i,j])
    areas=[float(np.linalg.norm(np.cross(p.xyz[:,1]-p.xyz[:,0],p.xyz[:,2]-p.xyz[:,0]),axis=1).sum()/2) for p in parts]
    total=sum(areas)
    if total<=0:raise MissingEvidence('Nonzero edited surface area required')
    support=sum(areas[i] for i in reached)/total
    return {'method':VERSION,'status':'measured','score':support*retention,'affects_validity':False,
        'scope':'Changed geometry contacting preserved supplied fixtures; inherited scene is not rebuilt or re-penalized',
        'contact_tolerance_m':tolerance,'geometry_preservation':retention,'support_fraction':support,
        'piece_count':len(parts),'supported_piece_count':len(reached),'anchor_count':len(anchors),
        'initial_scene_attachments':attachments,'contact_edges':links,'complete_triangle_pairs_tested':budget.pairs,
        'unsupported':[dict(identities[i],surface_area_m2=areas[i],score_weight=areas[i]/total)
                       for i in range(len(parts)) if i not in reached],
        'limitations':['Supplied unchanged fixtures are trusted support anchors, not a new certification of the initial scene.',
                       'Contact does not prove strength, deep penetration freedom, or correct semantic support selection.']}


def sky_sphere(evidence):
    """At most one small high isolated sphere, for the public lunar-Earth task.

    No name/role opt-out. Full vertices must fit a sphere within 2% radial RMS;
    the object must be compact, high and small compared to the terrain footprint.
    Appearance/blue color remains in the ordinary content evaluator.
    """
    objects=evidence.get('scene',{}).get('objects',{})
    meshes=visible_surfaces(objects)
    bounds=np.asarray([o.get('bounds') for o in meshes.values()],float)
    if bounds.shape!=(len(meshes),2,3) or not len(meshes) or not np.isfinite(bounds).all():return evidence,[]
    low,high=bounds[:,0].min(0),bounds[:,1].max(0);extent=high-low
    eligible=[]
    for name,obj in meshes.items():
        box=np.asarray(obj['bounds']);size=box[1]-box[0]
        if (size.min()<=0 or size.max()/size.min()>1.15 or size.max()>.1*max(extent[:2])
                or box[0,2]<low[2]+.5*extent[2]):continue
        surface=triangles(obj,evidence);points=np.unique(surface.reshape(-1,3),axis=0)
        if len(points)<12 or len(points)>100000:continue
        origin=points.mean(0);x=points-origin
        solution,*_=np.linalg.lstsq(np.column_stack((2*x,np.ones(len(x)))),np.sum(x*x,axis=1),rcond=None)
        center=origin+solution[:3];radii=np.linalg.norm(points-center,axis=1);radius=float(radii.mean())
        error=float(np.sqrt(np.mean((radii-radius)**2))/max(radius,1e-12))
        if error>.02 or len(pieces(surface,maximum_pieces=15000))!=1:continue
        budget=ContactBudget();part=Surface(surface)
        # Nearby geometry would make it an assembly part, not the isolated sky body.
        isolated=True
        for other,other_obj in meshes.items():
            if other==name:continue
            other_box=np.asarray(other_obj['bounds'])
            if np.any(other_box[0]>part.high+.02) or np.any(other_box[1]<part.low-.02):continue
            if contact(part,Surface(triangles(other_obj,evidence)),.02,budget):isolated=False;break
        if isolated:eligible.append((error,name,radius))
    if not eligible:return evidence,[]
    error,name,radius=min(eligible)
    filtered={**evidence,'scene':{**evidence['scene'],'objects':{n:o for n,o in objects.items() if n!=name}}}
    return filtered,[{'object':name,'sphere_radius_m':radius,'radial_rms_fraction':error,
                      'reason':'One isolated high sphere allowed by the lunar task; no semantic identity inferred'}]


def measure_physics(evidence,config):
    try:
        if config['scope']=='edit_delta':return edit_support(evidence,config)
        filtered,exceptions=sky_sphere(evidence) if config['sky_sphere_exception'] else (evidence,[])
        result=physical_plausibility(filtered,config['policy'])
        return {**result,'context_version':VERSION,'sky_exceptions':exceptions}
    except MissingEvidence as exc:
        return {'method':VERSION,'status':'not_measurable','score':0.,'reason':str(exc),'affects_validity':False}
