"""Continuous public-dimension measurements for L1 Text2Code 013.

The task leaves the horizontal origin free. Its XY datum is the midpoint of
the candidate's full surface extents. Only measured radii use that datum;
world Z is retained and no candidate-to-reference transformation is fitted.
Each declared ray remains in the denominator, including missing boundaries.
"""
import numpy as np
from scipy.special import logsumexp
from .continuous_numeric import line_intersections, scalar_error
from .continuous_surface import triangle_areas

DESIGN={'outer_radius_m':.018105,'bore_radius_m':.00795,'height_m':.0806,
        'groove_width_m':.00606,'groove_depth_m':.00221,'groove_center_z_m':.0508,
        'chamfer_m':.0009,'tolerance_m':.00015}
CONTRACT={'task_id':'L1/Text2Code/task_L1_Text2Code_013','design':DESIGN,
    'angles':64,'body_sections_m':[.005,.020,.040,.060,.075],
    'bore_sections':17,'groove_radial_fractions':[.2,.5,.8],
    'chamfer_axial_fractions':[.125,.375,.625,.875],
    'datum':'candidate surface XY extent midpoint; prescribed world Z unchanged',
    'registration':'none','kernel':'mean(2**(-max(abs(actual-target)-tolerance,0)/tolerance))'}


def numeric_measurements(vertices,triangles,evidence):
    if not evidence:raise ValueError('Bound geometry evidence required')
    v,f=np.asarray(vertices,float),np.asarray(triangles)
    area=triangle_areas(v,f)
    groups={k:[] for k in ('body_dimensions','through_bore','groove','chamfers')}
    if not len(area) or area.sum()<=0:
        return {'numeric_'+k:{'status':'absent','reason':'No positive-area sleeve surface','evidence':evidence} for k in groups}
    d=DESIGN;r,b,h,w,depth,z,c,t=(d[k] for k in ('outer_radius_m','bore_radius_m','height_m',
        'groove_width_m','groove_depth_m','groove_center_z_m','chamfer_m','tolerance_m'))
    used=v[np.unique(f)];lo,hi=used.min(0),used.max(0)
    origin=np.r_[(lo[:2]+hi[:2])/2,0.]
    angles=np.arange(CONTRACT['angles'])*2*np.pi/CONTRACT['angles']
    directions=np.column_stack([np.cos(angles),np.sin(angles),np.zeros(len(angles))])

    def add(group,identity,actual,expected,observation,tolerance=t):
        item={'id':identity,'actual':actual,'expected':expected,'tolerance_m':tolerance,'observation':observation}
        if actual is None:item.update(status='absent',reason='Required measured boundary or open corridor absent')
        else:item.update(status='measured',normalized_errors=scalar_error(actual,expected,tolerance))
        groups[group].append(item)

    def radius(height,side,index):
        point=origin+np.asarray([0,0,height]);hits=line_intersections(v,f,point,directions[index])
        positive=hits[hits>1e-9]
        # An annular sleeve has separate inner and outer boundaries on a ray.
        actual=None if len(positive)<2 else float(positive[0 if side=='inner' else -1])
        return actual,{'height_m':height,'angle_radians':float(angles[index]),'intersections_m':hits.tolist(),
                       'boundary':side,'datum_world_m':origin.tolist()}

    add('body_dimensions','overall_height',float(hi[2]-lo[2]),h,{'z_extents_m':[float(lo[2]),float(hi[2])]})
    add('body_dimensions','bottom_z',float(lo[2]),0.,{'world_z_m':float(lo[2])})
    # Equal groups within each numeric atom: height, placement and all body
    # diameter probes each receive one third; angular counts cannot drown them.
    for height in CONTRACT['body_sections_m']:
        for index in range(len(angles)):
            value,obs=radius(height,'outer',index)
            add('body_dimensions','outer_diameter',None if value is None else 2*value,2*r,obs)
    for height in np.linspace(c+t,h-c-t,CONTRACT['bore_sections']):
        for index in range(len(angles)):
            value,obs=radius(float(height),'inner',index)
            add('through_bore','bore_diameter',None if value is None else 2*value,2*b,obs)
    # Fixed disk rays check actual opening coverage, independently of radial
    # section diameters. An empty model cannot earn opening credit.
    for fraction in (.25,.5,.75):
        for index in range(len(angles)):
            check,_=radius(h/2,'inner',index)
            point=origin+directions[index]*b*fraction
            hits=line_intersections(v,f,point,[0,0,1])
            obstructed=hits[(hits>=-t)&(hits<=h+t)]
            add('through_bore','open_corridor',0. if check is not None and not len(obstructed) else None,0.,
                {'origin_world_m':point.tolist(),'vertical_intersections_m':hits.tolist()},tolerance=t)
    for index in range(len(angles)):
        value,obs=radius(z,'outer',index)
        add('groove','radial_depth',None if value is None else r-value,depth,obs)
        for fraction in CONTRACT['groove_radial_fractions']:
            point=origin+directions[index]*(r-depth+fraction*depth)+[0,0,z]
            hits=line_intersections(v,f,point,[0,0,1]);negative=hits[hits<-1e-9];positive=hits[hits>1e-9]
            values=None if not len(negative) or not len(positive) else [float(negative[-1]),float(positive[0])]
            obs={'origin_world_m':point.tolist(),'intersections_m':hits.tolist(),'radial_fraction':fraction}
            add('groove','axial_width',None if values is None else values[1]-values[0],w,obs)
            add('groove','axial_centre',None if values is None else z+sum(values)/2,z,obs)
    for end in ('bottom','top'):
        for fraction in CONTRACT['chamfer_axial_fractions']:
            dz=c*fraction;height=dz if end=='bottom' else h-dz
            for side,expected in (('inner',b+c-dz),('outer',r-c+dz)):
                for index in range(len(angles)):
                    value,obs=radius(height,side,index)
                    add('chamfers',end+'_'+side,value,expected,obs)
    results={}
    for name,rows in groups.items():
        # Each independent physical quantity has equal weight, and its frozen
        # spatial probes share that weight. Store both levels for replay.
        identities=list(dict.fromkeys(row['id'] for row in rows));quantities=[]
        for identity in identities:
            selected=[row for row in rows if row['id']==identity]
            errors=[]
            for row in selected:
                # Infinity would violate the finite-error contract. Observed
                # absences are retained explicitly at the subquantity level.
                errors.append({'status':row['status'],**({'reason':row['reason']} if row['status']=='absent'
                              else {'normalized_errors':row['normalized_errors']})})
            measured=[e for row in selected if row['status']=='measured' for e in row['normalized_errors']]
            if measured:
                # A log-mean-exp is exactly the effective normalized error
                # of this physical quantity. Missing rays contribute zero;
                # the denominator retains the complete fixed population.
                effective=float(-(logsumexp(-np.asarray(measured)*np.log(2))-np.log(len(selected)))/np.log(2))
                quantity={'status':'measured','normalized_errors':[max(0.,effective)],
                          'normalization':'negative_log2_mean_of_all_declared_ray_kernels'}
            else:quantity={'status':'absent','reason':'All probes for this physical quantity are absent'}
            quantities.append({'id':identity,'observations':errors,**quantity})
        results['numeric_'+name]={'status':'measured','quantities':quantities,'observations':rows,
            'evidence':evidence,'contract':CONTRACT,'datum_world_m':origin.tolist()}
    return results
