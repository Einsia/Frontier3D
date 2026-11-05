"""Count splayed support branches through persistent horizontal sections."""
import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .l2_cylindrical_components import section_segments,closed_loops


def measure(vertices,faces,*,sections=65,precision_m=1e-6):
    v=np.asarray(vertices,float);f=np.asarray(faces,int)
    if not len(f):return {'status':'measured','count':0,'components':[],'tracks':[],'section_observations':[]}
    if len(f)>500000:raise ValueError('Tripod section budget exceeded; no sampled fallback')
    surface=v[f];low=float(surface[:,:,2].min());high=float(surface[:,:,2].max());height=high-low
    if height<=precision_m: return {'status':'measured','count':0,'components':[],'tracks':[],'section_observations':[]}
    # These fixed ratios characterize support branches, independent of their
    # final placement. Geometry scoring retains the original world coordinates.
    levels=low+height*np.linspace(.005,.55,sections);step=float(levels[1]-levels[0])
    tracks=[];observations=[]
    for index,z in enumerate(levels):
        segments,_=section_segments(surface,np.array([0.,0.,1.]),z,precision_m/10)
        loops=closed_loops(segments[:,:,:2],precision_m)
        shapes=[Polygon(p) for p in loops if len(p)>=3]
        shapes=[p for p in shapes if p.is_valid and p.area>precision_m**2]
        union=unary_union(shapes)
        polygons=list(union.geoms) if union.geom_type=='MultiPolygon' else [union] if union.geom_type=='Polygon' and not union.is_empty else []
        polygons.sort(key=lambda p:(p.centroid.x,p.centroid.y))
        rows=[{'center_m':[float(p.centroid.x),float(p.centroid.y),float(z)],
               'area_m2':float(p.area),'equivalent_width_m':float(2*np.sqrt(p.area/np.pi)),
               'bounds_xy_m':list(p.bounds)} for p in polygons]
        observations.append({'index':index,'z_m':float(z),'regions':rows})
        active=[i for i,t in enumerate(tracks) if index-t['last_index']<=2]
        matched=set()
        if active and rows:
            cost=np.full((len(active),len(rows)),1e9)
            for a,i in enumerate(active):
                history=tracks[i]['observations'];last=history[-1];last_point=np.array(last['center_m']);predicted=last_point[:2]
                if len(history)>=2:
                    previous=np.array(history[-2]['center_m']);predicted=predicted+(last_point[:2]-previous[:2])*(z-last_point[2])/(last_point[2]-previous[2])
                for b,row in enumerate(rows):
                    width=max(last['equivalent_width_m'],row['equivalent_width_m'])
                    distance=float(np.linalg.norm(np.array(row['center_m'][:2])-predicted))
                    ratio=max(last['equivalent_width_m'],row['equivalent_width_m'])/min(last['equivalent_width_m'],row['equivalent_width_m'])
                    if distance<=max(2.5*width,10*step) and ratio<=4:
                        cost[a,b]=distance/max(width,step)+abs(np.log(ratio))*.1
            a,b=linear_sum_assignment(cost)
            for first,second in zip(a,b):
                if cost[first,second]>=1e9:continue
                track=tracks[active[first]];track['observations'].append(rows[second]);track['last_index']=index;matched.add(int(second))
        for i,row in enumerate(rows):
            if i not in matched:tracks.append({'first_index':index,'last_index':index,'observations':[row]})
    selected=[]
    minimum_span=.05*height
    for track in tracks:
        points=np.array([r['center_m'] for r in track['observations']]);widths=np.array([r['equivalent_width_m'] for r in track['observations']])
        evidence=None
        if points[0,2]>low+.25*height:continue
        # A branch can merge into a hub; retain its straight lower segment.
        for start in range(len(points)):
            minimum_end=int(np.searchsorted(points[:,2],points[start,2]+minimum_span))
            if minimum_end>=len(points):break
            for end in range(minimum_end,len(points)):
                section=points[start:end+1];delta=section[-1]-section[0];length=float(np.linalg.norm(delta))
                direction=delta/length;width=float(np.median(widths[start:end+1]))
                residual=np.linalg.norm(np.cross(section-section[0],direction),axis=1)
                lateral=float(np.linalg.norm(direction[:2]));vertical=float(abs(direction[2]))
                if (length>=3*width and np.sin(np.deg2rad(5))<=lateral and vertical>=np.sin(np.deg2rad(5))
                        and float(residual.max())<=max(.3*width,10*precision_m)):
                    evidence={'first':section[0].tolist(),'last':section[-1].tolist(),'axis':direction.tolist(),
                        'length_m':length,'median_width_m':width,'maximum_line_residual_m':float(residual.max()),
                        'first_observation':start,'last_observation':end}
                    break
            if evidence:break
        if evidence:
            selected.append({'track_index':tracks.index(track),'branch':evidence})
    return {'status':'measured','count':len(selected),'components':selected,'tracks':tracks,'section_observations':observations,
        'parameters':{'sections':sections,'height_m':height,'lower_fraction':.005,'upper_fraction':.55,
            'maximum_start_fraction':.25,'minimum_vertical_span_fraction':.05,'minimum_length_width_ratio':3,
            'minimum_splay_degrees':5,'maximum_splay_degrees':85,'line_residual_width_ratio':.3,'precision_m':precision_m},
        'scope':'Persistent slender splayed branches below the optical assembly; a central vertical column is excluded',
        'registration':'none','candidate_names_or_mesh_object_count_used_as_answers':False}
