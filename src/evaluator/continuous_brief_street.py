"""Continuous street clearance, corridor widths and actual frontage access."""
import heapq
import math
import numpy as np
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, box
from shapely import get_coordinates

from .continuous_brief_relations import surface, fractional, geometric_score
from .continuous_brief_numeric import interval_error, missing, actual_entities
from .continuous_brief_course_access import member_ids, projection, score
from .continuous_brief_heightfield_route import evidence_scene, array_sha
from .continuous_brief_route_regions import grid_radius, endpoint_mask, width_score, measure as route
from .continuous_brief_planar_route import planar_surface, blockers, polygons, coordinates as shape_coordinates
from .continuous_sceneedit_surface import join
from .l2_brief_relations import long_axis
from .l2_brief_route import build_grid
from .l2_reference_numeric import ray_distances
from .l2_surface_relief import VerticalSurface


SUPPORTED = {'l2_street_corridors', 'l2_street_clearance', 'l2_property_connections'}


def measuring_frame(roles, scene_objects, p):
    road = join([e['mesh'] for e in roles.get(p['road_role'], [])])
    if not len(road[1]): return None
    origin, length, width, along, across = long_axis(road[0][road[1]])
    basis = np.column_stack((across,along))
    def transformed(item):
        v,f=item;v=v.copy();v[:,:2]=(v[:,:2]-origin)@basis;return v,f
    selected = {k:[{**e,'mesh':transformed(e['mesh'])} for e in values] for k,values in roles.items()}
    objects = [(key,transformed(item)) for key,item in scene_objects]
    return selected,objects,float(length),float(width),{'origin_world_xy_m':origin.tolist(),
        'basis_columns_world_xy':basis.tolist(),'purpose':'Measuring coordinates along the actual road; no reference fitting or scene registration'}


def grid(roles, objects, selected_roles, p, cell):
    selected = [e for key in selected_roles for e in roles.get(key,[])]
    if not selected: return None
    floor = join([e['mesh'] for e in selected]); excluded=set().union(*(member_ids(e) for e in selected))
    scene=evidence_scene(floor,[(key,item) for key,item in objects if key not in excluded])
    return build_grid(scene,{**p,'road_role':'road'},cell)


def coordinates(shape,origin,cell):
    y,x=np.indices(shape);return x*cell+origin[0]+cell/2,y*cell+origin[1]+cell/2


def grid_proof(floor,free,origin,cell):
    return {'cell_size_m':cell,'shape':list(floor.shape),'origin_road_xy_m':origin.tolist(),
        'floor_sha256':array_sha(floor),'free_sha256':array_sha(free),
        'surface_cells':int(np.isfinite(floor).sum()),'free_cells':int(free.sum())}


def row_widths(free,rows,cell):
    values=[]
    for index in rows:
        edges=np.diff(np.r_[0,free[index].astype(np.int8),0])
        starts=np.flatnonzero(edges==1);ends=np.flatnonzero(edges==-1)
        values.append(float(np.max(ends-starts,initial=0)*cell))
    return values


def intrusion(roles,names,length,width,p,side=0):
    items=[e for name in names for e in roles.get(name,[])]
    domain=projection(join([e['mesh'] for e in items])[0][join([e['mesh'] for e in items])[1]]) if items else box(0,0,0,0)
    overlap=domain.intersection(box(-width,-length,width,length))
    if side:overlap=overlap.intersection(box(0 if side>0 else -width,-length,width if side>0 else 0,length))
    depth=0.
    for part in polygons(overlap):
        if part.area<=1e-12:continue
        low,_,high,_=part.bounds
        nearest=0. if low<=0<=high else min(abs(low),abs(high))
        depth=max(depth,width-nearest)
    observation=interval_error(depth,0.,0.,half_scale=p['contact_tolerance_m'])
    return 2.**-observation['normalized_error'],{'actual_penetration_m':depth,
        'overlap_area_m2':float(overlap.area),'observation':observation,'overlap':shape_coordinates(overlap)}


def line_parts(shape):
    if shape.geom_type=='LineString':return [shape]
    return [p for child in getattr(shape,'geoms',[]) for p in line_parts(child)]


def planar_corridor(roles,objects,names,side,length,width,required,p):
    entities=[e for name in names for e in roles.get(name,[])]
    if not entities:return missing('Required corridor surface absent')
    floor=join([e['mesh'] for e in entities])
    try:domain,z=planar_surface(floor)
    except ValueError:return None
    excluded=set().union(*(member_ids(e) for e in entities))
    obstacles=[(key,item) for key,item in objects if key not in excluded]
    occupied,_=blockers(obstacles,domain,z+p['surface_epsilon'],z+p['clearance_height'])
    xmin,_,xmax,_=domain.bounds
    if side:
        domain=domain.intersection(box(width if side>0 else xmin,-length,xmax if side>0 else -width,length))
    free=domain.difference(occupied)
    def section(y):return line_parts(free.intersection(LineString([(xmin-1,y),(xmax+1,y)])))
    inset=required/2+3*p['cell_size'];terminals=[]
    for sign in (-1,1):
        terminal=[]
        for part in section(sign*(length-inset)):
            xy=get_coordinates(part.interpolate(.5,normalized=True))[0]
            terminal.append([*xy,float(z)])
        terminals.append(terminal)
    raw=route(floor,obstacles,[{'start_points':terminals[0],'goal_points':terminals[1]}],
        {**p,'min_width':required,'max_snap':2e-6},[])
    # Explicitly test both actual end sections and every public longitudinal
    # sample. Disk-center insetting cannot conceal a pinched or short end.
    ys=np.linspace(-length+1e-6,length-1e-6,int(math.ceil(2*length/p['cell_size']))+1)
    widths=[max((part.length for part in section(y)),default=0.) for y in ys]
    minimum=min(widths,default=0.)
    cross=width_score(minimum,2e-6,required)
    q=min(score(raw['quantities'][0]),score(cross)) if minimum>0 else 0.
    return fractional(q,route=raw,section_width=cross,cross_section_y_m=ys.tolist(),
        cross_section_widths_m=widths,method='complete_planar_corridor_and_public_cross_sections')


def corridors(roles,objects,length,width,p):
    quantities=[]
    for names,sides,required in [([p['road_role']],[0],p['road_width_m']),
                                (p['sidewalk_roles'],[-1,1],p['sidewalk_width_m'])]:
        for side in sides:
            planar=planar_corridor(roles,objects,names,side,length,width,required,p)
            if planar is not None:
                if side:
                    limit,proof=intrusion(roles,names,length,width,p,side)
                    planar=fractional(min(score(planar),limit),width_measurement=planar,road_intrusion=proof)
                quantities.append({**planar,'side':side,'roles':names});continue
            rounds=[];cell=p['cell_size']
            for _ in range(12):
                data=grid(roles,objects,names,p,cell)
                if data is None:
                    row=missing('Required corridor surface absent');break
                floor,free,origin=data;x,y=coordinates(floor.shape,origin,cell)
                if side:free=free&(side*x>width)
                # Fixed actual road ends prevent a short sidewalk from choosing
                # a shorter test. Insetting only supplies disk-center endpoints.
                inset=required/2+3*p['cell_size'];distances=distance_transform_edt(free)*cell
                targets=[free&(np.abs(y-sign*(length-inset))<=.6*cell) for sign in (-1,1)]
                radius=grid_radius(floor,free,distances,*targets,cell,p)
                end_masks=[free&(np.abs(y-sign*(length-cell/2))<=cell) for sign in (-1,1)]
                connected_ends=grid_radius(floor,free,np.ones_like(floor),*end_masks,cell,p) is not None
                rows=np.flatnonzero(np.abs(y[:,0])<=length-cell/2+1e-8)
                sections=row_widths(free,rows,cell)
                full_extent=(origin[1]+cell/2<=-length+cell and origin[1]+(floor.shape[0]-.5)*cell>=length-cell)
                if radius is None or not connected_ends or not full_extent:
                    row=missing('Actual road ends are disconnected or surface extent is incomplete')
                else:
                    actual=min(2*radius,min(sections,default=0.))
                    row=width_score(actual,2*math.sqrt(2)*cell,p['road_width_m'] if not side else p['sidewalk_width_m'])
                proof=grid_proof(floor,free,origin,cell)
                rounds.append({**proof,'endpoints_connected':connected_ends,'full_extent':bool(full_extent),
                    'cross_section_y_m':y[rows,0].tolist(),'cross_section_widths_m':sections,'quantity':row})
                if row['status']=='absent' or np.ptp(row['continuous_score_interval'])<=.001:break
                cell/=2
            else:raise ValueError('Street corridor width remains numerically unresolved')
            if side:
                limit,proof=intrusion(roles,names,length,width,p,side)
                row=fractional(min(score(row),limit),width_measurement=row,road_intrusion=proof)
            quantities.append({**row,'side':side,'roles':names,'grid_rounds':rounds})
    return quantities


def clearance(roles,objects,p):
    quantities=[]
    for names in ([p['road_role']],p['sidewalk_roles']):
        data=grid(roles,objects,names,p,p['cell_size'])
        if data is None:
            quantities.append(missing('Required street surface absent',roles=names));continue
        floor,free,origin=data;total=int(np.isfinite(floor).sum())
        quantities.append(fractional(float(free.sum()/total) if total else 0.,roles=names,
            blocked_surface_cells=total-int(free.sum()),grid=grid_proof(floor,free,origin,p['cell_size']),
            coverage_definition='Fraction of actual sampled floor area with complete required height clearance'))
    return quantities


def widest_field(floor,free,distances,goals,cell,p):
    best=np.full(free.shape,-1.);pending=[]
    for y,x in zip(*np.nonzero(goals&free)):
        value=float(distances[y,x]);best[y,x]=value;heapq.heappush(pending,(-value,int(y),int(x)))
    step=p['max_step']+p['max_slope']*cell
    while pending:
        minus,y,x=heapq.heappop(pending);value=-minus
        if value<best[y,x]:continue
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
            ny,nx=y+dy,x+dx
            if (0<=ny<free.shape[0] and 0<=nx<free.shape[1] and free[ny,nx]
                    and abs(floor[ny,nx]-floor[y,x])<=step):
                other=min(value,float(distances[ny,nx]))
                if other>best[ny,nx]:best[ny,nx]=other;heapq.heappush(pending,(-other,ny,nx))
    return best


def facade_probes(house,entry,p,side):
    geometry=surface(house);low,high=geometry.min((0,1)),geometry.max((0,1))
    count=int(np.ceil((high[1]-low[1])/.1))+1
    if count>256:raise ValueError('House facade exceeds the fixed public 256-probe capacity')
    offset=p['entry_width_m']/2+3*p['cell_size'];rows=[]
    for along in np.linspace(low[1],high[1],count):
        hits=ray_distances(geometry,[0.,along,low[2]+.05],[side,0.,0.])
        if not len(hits):continue
        front=side*float(hits[0]);xs=front-side*np.linspace(p['contact_tolerance_m'],offset,33)
        xy=np.column_stack((xs,np.full(33,along)));z=entry.top(xy)
        if not np.isfinite(z).all():
            rows.append({'status':'absent','along_m':float(along),'reason':'Continuous facade-to-entry surface absent'});continue
        observations=[interval_error(float(abs(z[0]-low[2])),0.,p['max_step']+p['surface_epsilon'],
                                     half_scale=p['contact_tolerance_m'])]
        observations += [interval_error(float(abs(b-a)),0.,p['max_step']+p['max_slope']*abs(xs[1]-xs[0]),
                                        half_scale=p['contact_tolerance_m']) for a,b in zip(z[:-1],z[1:])]
        rows.append({'status':'measured','along_m':float(along),'endpoint':[float(xs[-1]),float(along),float(z[-1])],
            'points_road_xy_m':xy.tolist(),'heights_m':z.tolist(),'observations':observations,
            'contact_score':geometric_score(observations)})
    return rows


def connections(roles,objects,length,width,p,minimum_entities):
    houses,_=actual_entities(roles.get(p['house_role'],[]),volumetric=True)
    required=minimum_entities.get(p['house_role'],6)
    entries=roles.get(p['entry_role'],[])
    if not entries:return [missing('Required property entrance surface absent') for _ in range(max(required,len(houses)))]
    entries_mesh=join([e['mesh'] for e in entries]);entry=VerticalSurface(entries_mesh[0][entries_mesh[1]])
    walks=join([e['mesh'] for role in p['sidewalk_roles'] for e in roles.get(role,[])])
    if not len(walks[1]):return [missing('Actual sidewalk surface absent') for _ in range(max(required,len(houses)))]
    walk=VerticalSurface(walks[0][walks[1]])
    queries=[]
    for house in houses:
        geometry=surface(house);side=1 if float(geometry[:,:,0].min()+geometry[:,:,0].max())>=0 else -1
        queries.append({'house':house['id'],'side':side,'probes':facade_probes(house,entry,p,side)})
    intrusion_score,intrusion_proof=intrusion(roles,[p['entry_role']],length,width,p)
    cell=p['cell_size'];rounds=[]
    for _ in range(12):
        floor,free,origin=grid(roles,objects,[p['entry_role'],*p['sidewalk_roles']],p,cell)
        x,y=coordinates(floor.shape,origin,cell);fields={}
        for side in (-1,1):
            selected=free&(x*side>width);distance=distance_transform_edt(selected)*cell
            target=selected&(np.abs(y)<=cell)
            ys,xs=np.nonzero(target)
            z=walk.top(np.column_stack((x[ys,xs],y[ys,xs]))) if len(xs) else np.array([])
            target[ys,xs]&=np.isfinite(z)&(np.abs(z-floor[ys,xs])<=p['surface_epsilon'])
            fields[side]=widest_field(floor,selected,distance,target,cell,p)
        quantities=[];uncertain=False
        for query in queries:
            candidates=[];field=fields[query['side']]
            for probe in query['probes']:
                if probe['status']!='measured':continue
                mask=endpoint_mask(floor,free,[probe['endpoint']],origin,cell,{**p,'max_snap':2*p['cell_size']})
                radius=float(field[mask].max(initial=-1.))
                if radius<0:continue
                observed=width_score(2*radius,2*math.sqrt(2)*cell,p['entry_width_m'])
                bounds=[min(probe['contact_score'],v) for v in observed['continuous_score_interval']]
                candidates.append({'facade_probe':probe,'route_width':observed,'score_interval':bounds})
            interval=[min(intrusion_score,max((c['score_interval'][i] for c in candidates),default=0.)) for i in (0,1)]
            uncertain |= interval[1]-interval[0]>.001
            quantities.append(fractional(interval[0],house=query['house'],side=query['side'],
                continuous_score_interval=interval,facade_probes=query['probes'],connected_probes=candidates,
                road_intrusion=intrusion_proof,
                combination='Best actual facade connection; each connection uses the lesser contact and bottleneck-width score'))
        quantities += [missing('Required house access absent') for _ in range(max(0,required-len(houses)))]
        rounds.append({**grid_proof(floor,free,origin,cell),'widest_field_sha256':{str(s):array_sha(v) for s,v in fields.items()}})
        if not uncertain:break
        cell/=2
    else:raise ValueError('Property connection width remains numerically unresolved')
    quantities[0]['shared_grid_rounds']=rounds
    return quantities


def measure(check,roles,minimum_entities,scene_objects,evidence):
    p=check['params'];context=measuring_frame(roles,scene_objects,p)
    if context is None:return {'status':'absent','reason':'Actual road axis absent','evidence':evidence}
    selected,objects,length,width,frame=context;metric=check['metric']
    if metric=='l2_street_corridors':rows=corridors(selected,objects,length,width,p)
    elif metric=='l2_street_clearance':rows=clearance(selected,objects,p)
    elif metric=='l2_property_connections':rows=connections(selected,objects,length,width,p,minimum_entities)
    else:raise ValueError('Unsupported continuous street metric: '+metric)
    return {'status':'measured','quantities':rows,'evidence':evidence,'native_check':check,
        'measuring_frame':frame,'registration':'none','coordinate_space':'world_metres_with_explicit_measuring_basis',
        'scope':'Complete actual street triangles; finite public floor grid with continuous width/contact errors and area coverage'}
