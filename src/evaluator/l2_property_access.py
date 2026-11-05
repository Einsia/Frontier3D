"""Actual street corridors and house access from complete evaluated geometry."""
import numpy as np
from scipy.ndimage import distance_transform_edt,binary_propagation

from .l2_brief_relations import long_axis
from .l2_brief_route import build_grid,reachable
from .l2_course_access import area,clip_polygon
from .l2_reference_numeric import groups,triangles,ray_distances
from .l2_surface_relief import VerticalSurface
from .metrics import MissingEvidence,_register


COMMON='road_role sidewalk_roles house_role entry_role road_width_m sidewalk_width_m entry_width_m cell_size max_step max_slope surface_epsilon clearance_height contact_tolerance_m'


def local_geometry(evidence,p):
    road=np.concatenate([s for _,s in groups(evidence,p['road_role'])])
    origin,length,width,along,across=long_axis(road)
    rotation=np.column_stack((across,along));objects={}
    for name,obj in evidence['scene']['objects'].items():
        if obj.get('type')!='MESH' or not obj.get('visible_render') or not obj.get('faces'):continue
        surface=triangles(obj,evidence).copy();surface[:,:,:2]=(surface[:,:,:2]-origin)@rotation
        objects[name]={**obj,'geometry_evidence':{},'surface_triangles':surface,
            'bounds':[surface.min((0,1)).tolist(),surface.max((0,1)).tolist()]}
    return {**evidence,'scene':{**evidence['scene'],'objects':objects}},float(length),float(width)


def selected_grid(evidence,roles,p):
    # Candidate-authored role strings never nominate internal route members.
    objects={name:{**obj,'role':'__property_floor' if obj.get('role') in roles else None}
        for name,obj in evidence['scene']['objects'].items()}
    selected={**evidence,'scene':{**evidence['scene'],'objects':objects}}
    return build_grid(selected,{**p,'road_role':'__property_floor'},p['cell_size'])


def grid_points(shape,origin,cell):
    y,x=np.indices(shape)
    return x*cell+origin[0]+cell/2,y*cell+origin[1]+cell/2


def masks(free,p,width):
    distance=distance_transform_edt(free)*p['cell_size'];margin=p['cell_size']*np.sqrt(2)
    return free&(distance-margin>=width*.99/2),free&(distance+margin>=width*.99/2)


def point_at(floor,index,origin,cell):
    y,x=index;point=np.array([origin[0]+(x+.5)*cell,origin[1]+(y+.5)*cell,floor[y,x]])
    return {'low':point,'high':point}


def interior_overlap(evidence,roles,length,width):
    """Full triangle projection against the actual straight-road rectangle."""
    for role in roles:
        for _,surface in groups(evidence,role):
            for triangle in surface:
                poly=triangle[:,:2]
                for normal,limit in [([1,0],width),([-1,0],width),([0,1],length),([0,-1],length)]:
                    poly=clip_polygon(poly,np.asarray(normal,float),limit)
                    if len(poly)<3:break
                if area(poly)>1e-8:return True
    return False


def route_between_ends(floor,free,origin,length,width,p):
    cell=p['cell_size'];x,y=grid_points(floor.shape,origin,cell)
    safe,optimistic=masks(free,p,width);inset=width/2+3*cell
    def connected(mask,end_inset):
        endpoints=[]
        for sign in (-1,1):
            candidates=mask&(np.abs(y-sign*(length-end_inset))<=cell*.6)
            if not candidates.any():return False
            endpoints.append(candidates)
        # An interleaved node/edge grid enforces height continuity on every edge.
        # This avoids a Python search and a quadratic list of endpoint pairs.
        graph=np.zeros((2*mask.shape[0]-1,2*mask.shape[1]-1),bool);graph[::2,::2]=mask
        step=p['max_step']+p['max_slope']*cell
        heights=np.where(mask,floor,0.)
        graph[::2,1::2]=mask[:,:-1]&mask[:,1:]&(np.abs(np.diff(heights,axis=1))<=step)
        graph[1::2,::2]=mask[:-1,:]&mask[1:,:]&(np.abs(np.diff(heights,axis=0))<=step)
        starts=np.zeros_like(graph);starts[::2,::2]=endpoints[0]
        reached=binary_propagation(starts,mask=graph)[::2,::2]
        return bool(np.any(reached&endpoints[1]))
    passed=connected(safe,inset)
    actual_ends=connected(free,cell/2)
    if not passed and actual_ends and connected(optimistic,inset):
        raise MissingEvidence('Street corridor width lies within the published grid uncertainty')
    # Row-wise width includes the real ends that are inset for disk clearance.
    rows=np.flatnonzero(np.any(np.abs(y)<=length+1e-8,axis=1));thin=[];uncertain=False
    for row in rows:
        values=free[row].astype(np.int8)
        edges=np.diff(np.r_[0,values,0]);starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
        span=float(np.max(ends-starts,initial=0)*cell)
        if span+2*cell<width*.99:thin.append(float(y[row,0]))
        elif span-2*cell<width*.99:uncertain=True
    if passed and actual_ends and not thin and uncertain:
        raise MissingEvidence('Street end-section width lies within the published grid uncertainty')
    return bool(passed and actual_ends and not thin),{'connected':bool(passed),'actual_ends_connected':actual_ends,'insufficient_width_rows':thin[:20],
        'measured_longitudinal_rows':len(rows),'endpoint_inset_m':inset}


@_register('l2_street_corridors',COMMON)
def street_corridors(check,evidence,spec):
    p=check.params;e,length,width=local_geometry(evidence,p);rows=[]
    if interior_overlap(e,p['sidewalk_roles'],length,width):
        return 0.,{'reason':'Sidewalk surface intrudes into the actual road projection','corridors':[]}
    for roles,sides,required in [([p['road_role']],[0],p['road_width_m']),
            (p['sidewalk_roles'],[-1,1],p['sidewalk_width_m'])]:
        floor,free,origin=selected_grid(e,roles,p);x,y=grid_points(floor.shape,origin,p['cell_size'])
        # Pad rows to the actual road extent: a short path cannot shrink its own test.
        cell=p['cell_size']
        # Bounds are handled explicitly before connectivity, avoiding marker-based extents.
        covered_low=origin[1]+cell/2;covered_high=origin[1]+(floor.shape[0]-.5)*cell
        extent_ok=covered_low<=-length+cell and covered_high>=length-cell
        for side in sides:
            selected=free if not side else free&(x*side>width)
            passed,detail=route_between_ends(floor,selected,origin,length,required,p) if extent_ok else (False,{'reason':'Surface does not span actual road ends'})
            rows.append({'kind':'road' if not side else 'sidewalk','side':side,'passed':passed,**detail})
    return float(all(r['passed'] for r in rows)),{'corridors':rows,'endpoint_markers_used':False,
        'cell_size_m':p['cell_size'],'width_uncertainty_m':2*np.sqrt(2)*p['cell_size'],
        'scope':'Actual road axis and ends, both physical sides, finite height-field route and cross-sections; no door/frontage semantics'}


@_register('l2_street_clearance',COMMON)
def street_clearance(check,evidence,spec):
    p=check.params;e,_,_=local_geometry(evidence,p);rows=[]
    for roles in ([p['road_role']],p['sidewalk_roles']):
        floor,free,_=selected_grid(e,roles,p);blocked=np.isfinite(floor)&~free
        rows.append({'roles':roles,'surface_cells':int(np.isfinite(floor).sum()),'blocked_cells':int(blocked.sum()),'passed':not bool(blocked.any())})
    return float(all(r['passed'] for r in rows)),{'surfaces':rows,'clearance_height_m':p['clearance_height'],
        'cell_size_m':p['cell_size'],'scope':'Every rasterized road/sidewalk surface cell, including edges; finite conservative triangle coverage, not continuous volume certification'}


@_register('l2_property_connections',COMMON)
def property_connections(check,evidence,spec):
    p=check.params;e,length,width=local_geometry(evidence,p)
    entry=groups(e,p['entry_role']);entry_surface=np.concatenate([s for _,s in entry])
    if interior_overlap(e,[p['entry_role']],length,width):
        return 0.,{'properties':[],'reason':'Property access cannot use the road interior'}
    houses=groups(e,p['house_role']);index=VerticalSurface(entry_surface)
    floor,free,origin=selected_grid(e,[p['entry_role'],*p['sidewalk_roles']],p)
    safe,optimistic=masks(free,p,p['entry_width_m']);cell=p['cell_size']
    x,y=grid_points(floor.shape,origin,cell);walks=np.concatenate([s for role in p['sidewalk_roles'] for _,s in groups(e,role)])
    walk_index=VerticalSurface(walks);goals={}
    for side in (-1,1):
        candidates=np.argwhere(safe&(x*side>width))
        candidates=candidates[np.argsort(np.abs(y[candidates[:,0],candidates[:,1]]))]
        goal=None
        for at in candidates:
            xy=[x[tuple(at)],y[tuple(at)]];height=walk_index.top([xy])[0]
            if np.isfinite(height) and abs(height-floor[tuple(at)])<=p['surface_epsilon']:
                goal=point_at(floor,at,origin,cell);break
        goals[side]=goal
    rows=[];offset=p['entry_width_m']/2+3*cell
    for house,surface in houses:
        low,high=surface.min((0,1)),surface.max((0,1));side=-1 if high[0]<-width else 1 if low[0]>width else 0
        samples=min(257,int(np.ceil((high[1]-low[1])/.1))+1)
        if samples>=257:raise MissingEvidence('House facade exceeds 256 public horizontal probes')
        candidates=[]
        if side and goals[side] is not None:
            for along in np.linspace(low[1],high[1],samples):
                hits=ray_distances(surface,[0,along,low[2]+.05],[side,0,0])
                if not len(hits):continue
                front=side*float(hits[0]);xs=front-side*np.linspace(p['contact_tolerance_m'],offset,33)
                points=np.column_stack((xs,np.full(33,along)));heights=index.top(points)
                if not np.isfinite(heights).all() or abs(heights[0]-low[2])>p['max_step']+p['surface_epsilon']:continue
                if np.any(np.abs(np.diff(heights))>p['max_step']+p['max_slope']*abs(xs[1]-xs[0])):continue
                point=np.array([xs[-1],along,heights[-1]])
                candidates.append({'low':point,'high':point})
        passed=bool(candidates) and reachable(safe,floor,candidates,[goals[side]],origin,cell,{**p,'max_snap':2*cell})
        if not passed and candidates and reachable(optimistic,floor,candidates,[goals[side]],origin,cell,{**p,'max_snap':2*cell}):
            raise MissingEvidence('Property entry width lies within the published grid uncertainty')
        rows.append({'house':house['id'],'side':side,'facade_probes':samples,'geometric_contacts':len(candidates),'passed':bool(passed)})
    return float(all(r['passed'] for r in rows)),{'properties':rows,'entry_width_m':p['entry_width_m'],
        'cell_size_m':cell,'contact_tolerance_m':p['contact_tolerance_m'],
        'scope':'Actual low front surface reached by selected entry geometry and same-side sidewalk; shared/merged paths allowed. Door identity, interiors, structural support and sub-grid defects are not certified.'}


def validate(check):
    p=check.params
    for key in ('road_role','house_role','entry_role'):
        if not isinstance(p[key],str) or not p[key]:raise ValueError('Nonempty property geometry role required')
    if (not isinstance(p['sidewalk_roles'],list) or len(p['sidewalk_roles'])!=2
            or len(set(p['sidewalk_roles']))!=2 or not all(isinstance(r,str) and r for r in p['sidewalk_roles'])):
        raise ValueError('Two distinct sidewalk selection roles required')
    if len({p['road_role'],p['house_role'],p['entry_role'],*p['sidewalk_roles']})!=5:
        raise ValueError('Street geometry roles must be distinct')
    for key,(low,high) in {'road_width_m':(1,20),'sidewalk_width_m':(.5,5),'entry_width_m':(.3,5),
        'cell_size':(.005,.04),'max_step':(0,.1),'max_slope':(0,2),'surface_epsilon':(1e-6,.01),
        'clearance_height':(.5,3),'contact_tolerance_m':(.001,.05)}.items():
        if type(p[key]) not in (int,float) or not np.isfinite(p[key]) or not low<=p[key]<=high:
            raise ValueError('Invalid property access parameter: '+key)
    if p['cell_size']>min(p['entry_width_m'],p['sidewalk_width_m'])/16:
        raise ValueError('Grid cannot resolve the published pedestrian width')
