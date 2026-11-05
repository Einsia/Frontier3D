"""Finite geometric attachment and within-entity part checks, without text scoring."""
import numpy as np

from .l2_metrics import entities
from .l2_reference_numeric import groups,triangles
from .l2_surface_relief import VerticalSurface,footprint
from .metrics import MissingEvidence,_register


def surface_band(surface,grid=5):
    """Complete-surface lower/upper intersections on a public footprint grid."""
    origin,radii,rotation=footprint(surface)
    if min(radii)<=1e-8:raise MissingEvidence('Nondegenerate part footprint required')
    axis=np.linspace(-.8,.8,grid)
    local=np.array([[x,y] for y in axis for x in axis])*radii
    points=origin+local@rotation.T
    top=VerticalSurface(surface).top(points)
    reflected=surface.copy();reflected[:,:,2]*=-1
    bottom=-VerticalSurface(reflected).top(points)
    valid=np.isfinite(top)&np.isfinite(bottom)&(top-bottom>1e-5)
    return points,bottom,top,valid


def attachment_match(surface,base_index,params):
    points,bottom,top,valid=surface_band(surface,params['grid_size'])
    if int(valid.sum())<max(3,(len(points)+1)//2):
        return {'passed':False,'reason':'Insufficient actual finite-thickness attachment sections',
            'valid_sections':int(valid.sum()),'planned_sections':len(points)}
    base=base_index.top(points)
    height=top-bottom
    match=valid&np.isfinite(base)&(bottom<=base+params['max_gap_m'])
    match&=(top>=base+params['min_protrusion_m'])
    match&=(base-bottom<=height*params['maximum_embedded_fraction']+1e-8)
    fraction=float(match.sum()/valid.sum())
    return {'passed':fraction>=params['required_fraction'],'coverage':fraction,
        'valid_sections':int(valid.sum()),'matched_sections':int(match.sum()),'planned_sections':len(points),
        'finite_surface_thickness_m':[float(v) for v in height[valid]],
        'scope':'Finite footprint sections cross or touch the base top and protrude above it; not watertightness or mechanical stability'}


@_register('l2_attachment_correspondence',
    'base_role attachment_role minimum_distinct_bases grid_size max_gap_m min_protrusion_m maximum_embedded_fraction required_fraction')
def attachments(check,evidence,spec):
    p=check.params;bases=groups(evidence,p['base_role']);indexes=[VerticalSurface(s) for _,s in bases]
    attached=entities(evidence,p['attachment_role']);rows=[];owners=set();ambiguous=[]
    for entity in attached:
        surface=np.concatenate([triangles(obj,evidence) for _,obj in entity['members']])
        matches=[];probes=[]
        for (base,_),index in zip(bases,indexes):
            result=attachment_match(surface,index,p);probes.append({'base':base['id'],**result})
            if result['passed']:matches.append(base['id'])
        if len(matches)==1:owners.add(matches[0])
        else:ambiguous.append(entity['id'])
        rows.append({'attachment':entity['id'],'matching_bases':matches,'base_probes':probes})
    return float(len(owners)>=p['minimum_distinct_bases'] and not ambiguous),{
        'distinct_bases':sorted(owners),'distinct_base_count':len(owners),'attachments':rows,'unassigned_or_ambiguous':ambiguous,
        'names_or_parents_used_as_correspondence':False,'threshold_status':'published_pilot_pending_calibration',
        'scope':'Actual geometric attachment to distinct role-selected base entities; no semantic chimney/house classification'}


def clip_height(surface,level,above):
    """Clip every triangle to a Z half-space without relying on object splits."""
    result=[]
    for triangle in surface:
        polygon=[]
        for i,a in enumerate(triangle):
            b=triangle[(i+1)%3];inside_a=a[2]>=level if above else a[2]<=level
            inside_b=b[2]>=level if above else b[2]<=level
            if inside_a:polygon.append(a)
            if inside_a!=inside_b:
                polygon.append(a+(b-a)*((level-a[2])/(b[2]-a[2])))
        for i in range(1,len(polygon)-1):result.append([polygon[0],polygon[i],polygon[i+1]])
    return np.asarray(result,float).reshape(-1,3,3)


def grave_parts(surface,p):
    normal=np.cross(surface[:,1]-surface[:,0],surface[:,2]-surface[:,0]);area=np.linalg.norm(normal,axis=1)/2
    low=float(surface[:,:,2].min());high=float(surface[:,:,2].max())
    planar=(np.ptp(surface[:,:,2],axis=1)<=1e-5)&(np.abs(normal[:,2])>1e-12)
    height=surface.mean(axis=1)[:,2];levels=np.unique(np.round(height[planar],5))
    if len(levels)>128:raise MissingEvidence('Part decomposition exceeds 128 horizontal levels')
    candidates=[]
    for level in levels:
        if not low+1e-5<level<high-p['min_protrusion_m']+1e-8:continue
        bed_faces=surface[planar&(np.abs(height-level)<=1e-5)]
        origin,radii,rotation=footprint(bed_faces)
        lower_height=level-low
        if lower_height>p['horizontal_max_height_ratio']*2*min(radii):continue
        bed_area=float(area[planar&(np.abs(height-level)<=1e-5)].sum())
        if bed_area<p['minimum_bed_area_fraction']*4*np.prod(radii):continue
        upper=clip_height(surface,level+1e-5,True)
        if not len(upper):continue
        try:_,upper_radii,_=footprint(upper)
        except MissingEvidence:continue
        span=high-level
        upright=span>=p['upright_min_height_ratio']*2*max(upper_radii)
        # Non-coplanar full upper geometry is required, not a tilted image plane.
        points=np.unique(upper.reshape(-1,3),axis=0)
        solid=bool(min(upper_radii)>1e-5 and np.linalg.matrix_rank(points-points.mean(0),tol=1e-7)==3)
        offset=np.abs((points[:,:2]-origin)@rotation)
        margin=p['maximum_part_offset_fraction']*2*max(radii)
        nearby=bool(np.all(offset<=radii+margin+1e-8))
        attached=bool(float(upper[:,:,2].min())<=level+p['max_gap_m']+2e-5)
        # The rounded level groups faces; clipping at it would remove a real
        # float32 bed top (e.g. 0.200000003). Keep the measured face height.
        lower=clip_height(surface,float(bed_faces[:,:,2].max()),False)
        _,_,_,valid=surface_band(lower,p['grid_size'])
        lower_solid=int(valid.sum())>=max(3,(len(valid)+1)//2)
        passed=bool(upright and solid and nearby and attached and lower_solid)
        candidates.append({'passed':passed,'bed_top_m':float(level),'bed_height_m':float(lower_height),
            'bed_horizontal_spans_m':(2*radii).tolist(),'bed_plane_area_m2':bed_area,
            'upright_height_m':float(span),'upright_horizontal_spans_m':(2*upper_radii).tolist(),
            'upright_proportion_passed':bool(upright),'upright_non_coplanar':solid,
            'near_same_bed':nearby,'base_level_passed':attached,'bed_finite_thickness_passed':lower_solid})
    return {'passed':any(c['passed'] for c in candidates),'candidate_decompositions':candidates,
        'part_tags_or_mesh_splits_used_as_answers':False}


@_register('l2_entity_part_geometry',
    'role grid_size max_gap_m min_protrusion_m horizontal_max_height_ratio upright_min_height_ratio minimum_bed_area_fraction maximum_part_offset_fraction')
def entity_parts(check,evidence,spec):
    rows=[{'entity':entity['id'],**grave_parts(surface,check.params)} for entity,surface in groups(evidence,check.params['role'])]
    return float(bool(rows) and all(row['passed'] for row in rows)),{'entities':rows,
        'selection':'Public whole-entity role; geometric horizontal-level decomposition independent of names, mesh splits and part tags',
        'threshold_status':'published_pilot_pending_calibration',
        'scope':'Finite horizontal-bed and nearby upright-volume decomposition; not marker symbolism, curved beds, full connectivity or ground stability'}


def validate(check):
    p=check.params
    for key in ('base_role','attachment_role','role'):
        if key in p and (not isinstance(p[key],str) or not p[key]):raise ValueError('Nonempty assembly selector required')
    if check.metric=='l2_attachment_correspondence':
        if p['base_role']==p['attachment_role']:raise ValueError('Distinct base and attachment roles required')
        if type(p['minimum_distinct_bases']) is not int or p['minimum_distinct_bases']<1:raise ValueError('Positive base count required')
    if type(p['grid_size']) is not int or not 3<=p['grid_size']<=17:raise ValueError('Assembly grid must be 3..17')
    limits={'max_gap_m':(0,.1),'min_protrusion_m':(1e-4,1),'maximum_embedded_fraction':(0,.75),
        'required_fraction':(.5,1),'horizontal_max_height_ratio':(.05,.5),'upright_min_height_ratio':(.5,2.),'minimum_bed_area_fraction':(.1,1),'maximum_part_offset_fraction':(0,.5)}
    for key,(low,high) in limits.items():
        if key in p and (type(p[key]) not in (int,float) or not np.isfinite(p[key]) or not low<=p[key]<=high):
            raise ValueError('Invalid assembly parameter: '+key)
