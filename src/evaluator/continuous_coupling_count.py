"""Count carriage ends with narrow central 3D extensions beyond the cargo body.

The longitudinal axis is an observed body feature. Coordinates are projected
only for cross-section measurement; no candidate-to-reference transform occurs.
"""
import numpy as np
from shapely.geometry import MultiPoint
from .continuous_surface import triangle_areas
from .l2_cylindrical_components import section_segments,closed_loops


def measure(vertices,faces,*,sections=33,precision_m=1e-6):
    if sections<9 or precision_m<=0:raise ValueError('Dense cross-sections and positive precision required')
    v=np.asarray(vertices,float);f=np.asarray(faces,int)
    if len(f)>500000:raise ValueError('Coupling geometry budget exceeded')
    parameters={'sections':sections,'precision_m':precision_m,'upper_body_fraction':.35,
        'minimum_body_length_width_ratio':1.5,'scan_depth_over_body_width':.5,
        'maximum_first_section_gap_over_body_width':.15,'minimum_consecutive_sections':3,
        'maximum_section_width_over_body_width':.5,'maximum_section_height_over_full_height':.3,
        'maximum_center_offset_over_body_width':.15,'maximum_section_top_over_full_height':.6}
    result={'status':'measured','count':0,'components':[],'observations':[],
        'parameters':parameters,'registration':'none','candidate_names_or_mesh_object_count_used_as_answers':False,
        'scope':'number of carriage ends with a narrow central solid protrusion; shape, placement and appearance scored separately'}
    if not len(f):return {**result,'reason':'No added geometry'}
    areas=triangle_areas(v,f);surface=v[f];positive=areas>precision_m**2
    if not positive.any():return {**result,'reason':'No positive-area added surface'}
    used=surface[positive].reshape(-1,3);zmin,zmax=used[:,2].min(),used[:,2].max();height=zmax-zmin
    if height<=10*precision_m:return {**result,'reason':'No volumetric cargo-body context'}
    upper=surface[positive & (surface[:,:,2].mean(1)>=zmax-.35*height)]
    if not len(upper):return {**result,'reason':'No observed upper body surface'}
    points=np.unique(upper.reshape(-1,3),axis=0)[:,:2];center=points.mean(0)
    if len(points)<3:return {**result,'reason':'No two-dimensional upper cargo-body footprint'}
    envelope=MultiPoint(points).minimum_rotated_rectangle
    if envelope.geom_type!='Polygon':return {**result,'reason':'Upper cargo-body footprint has no area'}
    corners=np.asarray(envelope.exterior.coords)[:4]
    edges=np.roll(corners,-1,axis=0)-corners;lengths=np.linalg.norm(edges,axis=1)
    long=edges[int(np.argmax(lengths))]/lengths.max()
    if long[np.argmax(abs(long))]<0:long=-long
    across=np.array([-long[1],long[0]]);frame=np.column_stack([long,across])
    projected=(points-center)@frame;low,high=projected.min(0),projected.max(0)
    length,width=high-low
    if width<=10*precision_m or length<1.5*width:
        return {**result,'reason':'Upper geometry lacks an elongated rectangular carriage-body frame',
                'observed_body_length_m':float(length),'observed_body_width_m':float(width)}
    lateral_center=(low[1]+high[1])/2
    projected_vertices=np.column_stack([(v[:,:2]-center)@frame,v[:,2]])
    projected_surface=projected_vertices[f]
    result['body']={'origin_xy_m':center.tolist(),'longitudinal_axis_xy':long.tolist(),
        'across_axis_xy':across.tolist(),'bounds_in_measurement_frame_m':[low.tolist(),high.tolist()],
        'full_z_bounds_m':[float(zmin),float(zmax)],'length_m':float(length),'width_m':float(width),
        'axis_definition':'long edge of the minimum-area upper-body footprint rectangle; no reference fit'}
    for sign,end in [(-1,low[0]),(1,high[0])]:
        observed=[];run=0;best=0;first=None
        for i in range(sections):
            outward=(i+.5)*.5*width/sections;position=end+sign*outward
            segments,_=section_segments(projected_surface,np.array([1.,0.,0.]),position,precision_m)
            loops=closed_loops(segments[:,:,1:],precision_m);qualifying=[];rejected=[]
            for polygon in loops:
                a,b=polygon.min(0),polygon.max(0);w,h=b-a
                centre=(a+b)/2
                area=abs(float(np.sum(polygon[:,0]*np.roll(polygon[:,1],-1)-polygon[:,1]*np.roll(polygon[:,0],-1))))/2
                okay=(min(w,h)>10*precision_m and area>100*precision_m**2 and w<=.5*width
                    and h<=.3*height and abs(centre[0]-lateral_center)<=.15*width
                    and b[1]<=zmin+.6*height and a[1]>=zmin-precision_m)
                row={'polygon_across_z_m':polygon.tolist(),'bounds_m':[a.tolist(),b.tolist()],
                     'area_m2':area,'width_m':float(w),'height_m':float(h),'qualifies':bool(okay)}
                (qualifying if okay else rejected).append(row)
            if qualifying:
                run+=1;best=max(best,run)
                if first is None:first=outward
            else:run=0
            observed.append({'index':i,'longitudinal_offset_m':float(position),'outward_distance_m':float(outward),
                'qualifying_sections':qualifying,'rejected_sections':rejected})
        qualifies=best>=3 and first is not None and first<=.15*width
        row={'end':int(sign),'qualifies':bool(qualifies),'maximum_consecutive_sections':best,
             'first_protrusion_distance_m':None if first is None else float(first),'sections':observed}
        result['observations'].append(row)
        if qualifies:result['components'].append(row)
    result['count']=len(result['components'])
    return result
