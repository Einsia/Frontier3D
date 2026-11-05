"""Prototype bar observations; not a validated semantic heated-iron counter.

The SceneEdit 004 adapter remains incomplete: reference structural beams and
iron pieces share these geometric traits. Do not publish this count as its N.
"""
import numpy as np
from shapely.geometry import MultiPoint
from .continuous_outline_count import parts, planar_frame
from .continuous_sceneedit_surface import triangle_keys


def measure(vertices, faces, *, maximum_width_m, precision_m=1e-6, face_warm=None):
    if maximum_width_m <= 0 or precision_m <= 0: raise ValueError('Positive reference scales required')
    observations=[];components=[];unknown=[]
    warmth={}
    if face_warm is not None:
        if len(face_warm)!=len(faces):raise ValueError('One appearance observation per source triangle required')
        for key,warm in zip(triangle_keys(vertices,faces),face_warm):
            code=key.tobytes();warmth[code]=max(warmth.get(code,-1),int(warm))
    for index,(v,f) in enumerate(parts(vertices,faces)):
        if len(v)<4:continue
        center,basis,spans=planar_frame(v)
        if max(spans[1:])<=10*precision_m:continue
        rectangle=MultiPoint((v-center)@basis[1:].T).minimum_rotated_rectangle
        if rectangle.geom_type!='Polygon':continue
        corners=np.array(rectangle.exterior.coords)[:4]
        widths=np.linalg.norm(np.roll(corners,-1,axis=0)-corners,axis=1)[:2]
        row={'part_index':index,'center_m':center.tolist(),'principal_spans_m':spans.tolist(),
             'cross_section_widths_m':widths.tolist(),'length_width_ratio':float(spans[0]/max(widths))}
        if not (min(widths)>10*precision_m and row['length_width_ratio']>=3
                and max(widths)<=maximum_width_m):
            observations.append({**row,'qualifies':False,'reason':'Requires a slender solid bar at the frozen reference scale'});continue
        points,inverse=np.unique(v,axis=0,return_inverse=True);indexed=inverse[f]
        edges=np.sort(np.concatenate([indexed[:,[0,1]],indexed[:,[1,2]],indexed[:,[2,0]]]),axis=1)
        _,counts=np.unique(edges,axis=0,return_counts=True)
        closed=bool(np.all(counts==2))
        triangles=v[f];cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        area2=np.linalg.norm(cross,axis=1);valid=area2>precision_m**2
        normals=cross[valid]/area2[valid,None];area=area2[valid]/2
        side=abs(normals@basis[0])<.25
        projected=normals[side]@basis[1:].T;angles=np.arctan2(projected[:,1],projected[:,0]);weights=area[side]
        best=0.
        for angle in angles:
            deviation=abs((angles-angle+np.pi/4)%(np.pi/2)-np.pi/4)
            fraction=float(weights[deviation<=np.deg2rad(12)].sum()/weights.sum()) if weights.sum() else 0.
            best=max(best,fraction)
        markers=np.array([warmth.get(k.tobytes(),0) for k in triangle_keys(v,f)])[valid]
        warm_fraction=float(area[markers==1].sum()/area.sum()) if area.sum() else 0.
        unknown_fraction=float(area[markers<0].sum()/area.sum()) if area.sum() else 0.
        qualifies=closed and (best>=.7 or warm_fraction>=.5)
        row.update(closed_triangle_edges=closed,rectangular_side_area_fraction=best,qualifies=qualifies,
            warm_surface_fraction=warm_fraction,unknown_appearance_fraction=unknown_fraction,
            reason='Closed slender neutral rectangular bar or warm iron rod' if qualifies else 'Requires a rectangular clay bar or demonstrated warm iron appearance')
        observations.append(row)
        if qualifies:components.append(row)
        elif closed and unknown_fraction>0:unknown.append(row)
    return {'status':'not_measurable' if unknown else 'measured','count':len(components),'components':components,'observations':observations,
        'unclassified_appearance':unknown,
        'parameters':{'maximum_width_m':maximum_width_m,'precision_m':precision_m,
            'minimum_length_width_ratio':3.,'side_normal_angle_tolerance_degrees':12.,'minimum_rectangular_side_area_fraction':.7},
        'registration':'none','candidate_names_or_mesh_object_count_used_as_answers':False}
