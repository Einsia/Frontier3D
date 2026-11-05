"""Count recessed garage entries in a reviewed pit-building row.

Cross-section voids must have a low sill, a roof and side boundaries. Complete
triangle rays establish an open approach, a recessed back and floor/roof depth.
All coordinates remain in the supplied world frame; the local basis only sets
measurement directions. These finite probes do not certify vehicle clearance.
"""
import numpy as np
from shapely.geometry import Polygon, MultiPoint, Point
from shapely.ops import unary_union
from shapely import make_valid, union_all
from .continuous_outline_count import parts
from .l2_cylindrical_components import section_segments, closed_loops
from .l2_reference_numeric import ray_distances


def polygon_parts(geometry):
    if geometry.geom_type=='Polygon':return [geometry]
    return [p for g in getattr(geometry,'geoms',[]) for p in polygon_parts(g)]


def section(parts_surface, along, inward, offset, precision):
    occupied=[];arrangements=[]
    for surface in parts_surface:
        segments,_=section_segments(surface,inward,offset,precision)
        projected=np.stack((segments@along,segments[:,:,2]),axis=-1)
        region=Polygon();loops=[]
        for loop in closed_loops(projected,precision):
            polygon=Polygon(loop)
            if not polygon.is_valid:
                # Resolve self-touching section walks as an exact planar line
                # arrangement. Never move the input mesh or buffer its walls.
                repaired=make_valid(polygon)
                polygon=unary_union(polygon_parts(repaired))
                arrangements.append({'original_section_loop_m':loop.tolist(),
                    'resolved_polygons_m':[np.asarray(p.exterior.coords).tolist() for p in polygon_parts(polygon)]})
            loops.extend(polygon_parts(polygon))
        # Nested loops describe cavities; partially overlapping solid sections
        # describe their union. XOR would carve false gaps in overlapping beams.
        loops.sort(key=lambda p:-p.area)
        for i,polygon in enumerate(loops):
            depth=sum(previous.covers(polygon) for previous in loops[:i])
            region=region.difference(polygon) if depth%2 else region.union(polygon)
        if not region.is_empty:occupied.append(region)
    # Evaluated float32 wall/floor contacts may differ by micrometres. Boolean
    # sections use the declared fixed metric grid; source triangles and ray
    # measurements retain their original world coordinates.
    union=union_all(occupied,grid_size=precision)
    return [Polygon(hole) for polygon in polygon_parts(union) for hole in polygon.interiors],arrangements


def approach_regions(surface,polygon,along,inward,offset,sign,precision):
    """Project the complete front-side triangles to find genuinely open areas."""
    blockers=[]
    distance=sign*(surface@inward-offset)
    for triangle,distances in zip(surface[distance.min(1)<0],distance[distance.min(1)<0]):
        clipped=[]
        for i,j in ((0,1),(1,2),(2,0)):
            if distances[i]<=0:clipped.append(triangle[i])
            if (distances[i]<0)!=(distances[j]<0) and distances[i]!=distances[j]:
                clipped.append(triangle[i]+distances[i]/(distances[i]-distances[j])*(triangle[j]-triangle[i]))
        if len(clipped)<3:continue
        points=np.asarray(clipped);projected=Polygon(np.column_stack((points@along,points[:,2])))
        if projected.area>precision**2:
            blockers.extend(polygon_parts(projected if projected.is_valid else make_valid(projected)))
    return polygon_parts(polygon.difference(unary_union(blockers)))


def entry_rays(surface,polygon,along,inward,offset,depth_bounds,height,precision):
    """Observe both directions; front piers may divide a single garage opening."""
    observations=[]
    for sign in (-1,1):
        outside_distance=(offset-depth_bounds[0]) if sign==1 else (depth_bounds[1]-offset)
        for opening in approach_regions(surface,polygon,along,inward,offset,sign,precision):
            x0,z0,x1,z1=opening.bounds
            if x1-x0<.2*height or z1-z0<.4*height or opening.area<.5*(x1-x0)*(z1-z0):continue
            rows=[];valid=True
            for x in np.linspace(x0,x1,5)[1:-1]:
                for z in np.linspace(z0,z1,5)[1:-1]:
                    if not opening.contains(Point(x,z)):continue
                    origin=along*x+inward*offset+np.array([0.,0.,z])
                    front=ray_distances(surface,origin,-sign*inward);back=ray_distances(surface,origin,sign*inward)
                    clear=not len(front) or front[0]>outside_distance+10*precision
                    recess=float(back[0]) if len(back) else None
                    passed=bool(clear and recess is not None and recess>=.1*(depth_bounds[1]-depth_bounds[0]))
                    rows.append({'origin_m':origin.tolist(),'front_first_hit_m':float(front[0]) if len(front) else None,
                        'outside_distance_m':float(outside_distance),'back_first_hit_m':recess,'passed':passed})
                    valid &= passed
            supports=[]
            if valid and len(rows)>=5:
                x,z=opening.representative_point().coords[0];center=along*x+inward*offset+np.array([0.,0.,z])
                back=ray_distances(surface,center,sign*inward)
                if not len(back):valid=False
                else:
                    for fraction in (.25,.5,.75):
                        point=center+sign*inward*float(back[0])*fraction
                        down=ray_distances(surface,point,[0,0,-1]);up=ray_distances(surface,point,[0,0,1])
                        passed=bool(len(down) and len(up) and down[0]+up[0]<=height+10*precision)
                        supports.append({'origin_m':point.tolist(),'floor_distance_m':float(down[0]) if len(down) else None,
                            'roof_distance_m':float(up[0]) if len(up) else None,'passed':passed})
                        valid &= passed
            else:valid=False
            observations.append({'inward_sign':sign,'approach_polygon_row_z_m':np.asarray(opening.exterior.coords).tolist(),
                'rays':rows,'interior_floor_roof_probes':supports,'qualifies':bool(valid)})
    return observations


def _orientation(vertices,faces,*,sections,precision_m,minimum_consecutive_sections,row_axis_choice):
    if sections<9 or not 2<=minimum_consecutive_sections<=sections or precision_m<=0:
        raise ValueError('Positive precision and sufficient declared sections required')
    if len(faces)>500000:raise ValueError('Garage section budget exceeded')
    v=np.asarray(vertices,float);f=np.asarray(faces,int)
    parameters={'sections':sections,'precision_m':precision_m,'minimum_consecutive_sections':minimum_consecutive_sections}
    result={'count':0,'components':[],'sections':[],'parameters':parameters,'registration':'none',
        'section_boolean_precision_m':precision_m,
        'candidate_names_or_mesh_object_count_used_as_answers':False,
        'scope':'Recessed 3D openings in the complete reviewed building row; up to nine approach rays and three interior floor/roof pairs per observed opening'}
    if not len(f):return result
    used=v[np.unique(f)];height=float(np.ptp(used[:,2]));rectangle=MultiPoint(used[:,:2]).minimum_rotated_rectangle
    if rectangle.geom_type!='Polygon' or height<=100*precision_m:return result
    corners=np.asarray(rectangle.exterior.coords)[:4];edges=np.roll(corners,-1,axis=0)-corners
    edge=edges[np.argmax(np.linalg.norm(edges,axis=1))];along=np.r_[edge/np.linalg.norm(edge),0.]
    if row_axis_choice:along=np.cross([0.,0.,1.],along)
    if along[np.argmax(abs(along))]<0:along=-along
    inward=np.cross([0.,0.,1.],along);projection=used@inward;low,high=map(float,[projection.min(),projection.max()])
    if high-low<=100*precision_m:return result
    result['measurement_frame']={'row_axis':along.tolist(),'depth_axis':inward.tolist(),
        'depth_bounds_m':[low,high],'vertical_bounds_m':[float(used[:,2].min()),float(used[:,2].max())]}
    meshes=parts(v,f);surfaces=[vv[ff] for vv,ff in meshes];surface=np.concatenate(surfaces)
    tracks=[]
    for i,offset in enumerate(np.linspace(low+.02*(high-low),high-.02*(high-low),sections)):
        voids,arrangements=section(surfaces,along,inward,float(offset),precision_m)
        record={'index':i,'offset_m':float(offset),'openings':[],'resolved_planar_arrangements':arrangements}
        assigned=set()
        for polygon in voids:
            x0,z0,x1,z1=map(float,polygon.bounds);width=x1-x0;h=z1-z0
            if h<.4*height or width<.2*height or z0>used[:,2].min()+.3*height:continue
            rays=entry_rays(surface,polygon,along,inward,float(offset),(low,high),height,precision_m)
            qualified=any(r['qualifies'] for r in rays)
            row={'polygon_row_z_m':np.asarray(polygon.exterior.coords).tolist(),'bounds_row_z_m':[x0,z0,x1,z1],
                'rays':rays,'qualifies':qualified};record['openings'].append(row)
            if not qualified:continue
            candidates=[]
            for j,track in enumerate(tracks):
                if j in assigned or track['section_indices'][-1]!=i-1:continue
                previous=track['last_polygon'];intersection=previous.intersection(polygon).area
                overlap=intersection/max(previous.area,polygon.area)
                if overlap>=.5:candidates.append((overlap,j))
            if candidates:
                j=max(candidates)[1];track=tracks[j];track['section_indices'].append(i);track['bounds'].append([x0,z0,x1,z1]);track['last_polygon']=polygon
            else:
                j=len(tracks);tracks.append({'section_indices':[i],'bounds':[[x0,z0,x1,z1]],'last_polygon':polygon})
            assigned.add(j)
        result['sections'].append(record)
    for track in tracks:
        if len(track['section_indices'])<minimum_consecutive_sections:continue
        bounds=np.asarray(track['bounds']);interval=[float(bounds[:,0].min()),float(bounds[:,2].max())]
        row={'section_indices':track['section_indices'],'row_interval_m':interval,'bounds_row_z_m':track['bounds']}
        # A bay observed in multiple separated depth runs still denotes one
        # opening. Parallel openings with disjoint row spans remain distinct.
        matches=[]
        for component in result['components']:
            a,b=component['row_interval_m'];overlap=max(0.,min(b,interval[1])-max(a,interval[0]))
            if overlap>=.5*min(b-a,interval[1]-interval[0]):matches.append(component)
        if not matches:result['components'].append({**row,'additional_runs':[]})
        else:
            merged={'section_indices':row['section_indices'],'bounds_row_z_m':row['bounds_row_z_m'],
                'row_interval_m':[min(interval[0],*(m['row_interval_m'][0] for m in matches)),
                                  max(interval[1],*(m['row_interval_m'][1] for m in matches))],
                'additional_runs':matches}
            result['components']=[c for c in result['components'] if c not in matches]+[merged]
    result['count']=len(result['components']);return result


def measure(vertices,faces,*,sections=49,precision_m=1e-5,minimum_consecutive_sections=3):
    parameters={'sections':sections,'precision_m':precision_m,'minimum_consecutive_sections':minimum_consecutive_sections}
    axes=[_orientation(vertices,faces,**parameters,row_axis_choice=i) for i in range(2)]
    selected=max(range(2),key=lambda i:axes[i]['count'])
    result=dict(axes[selected]);result['selected_intrinsic_axis']=selected
    result['axis_selection']='Maximum distinct demonstrated entries over the two intrinsic footprint axes; no reference pose or expected count is used'
    result['alternative_axis_observation']=axes[1-selected]
    return result
