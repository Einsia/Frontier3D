"""Geometric count inside an independently reviewed iron-workpiece region.

Semantic selection belongs to a hash-bound review. This kernel checks the
complete selected geometry and counts closed, volumetric, elongated bodies.
It never derives a count from object labels, material color or mesh splits.
"""
import numpy as np
from shapely.geometry import MultiPoint
from .continuous_outline_count import parts, planar_frame


def measure(vertices, faces, *, precision_m=1e-6, minimum_length_width_ratio=3.):
    if precision_m<=0 or minimum_length_width_ratio<=1:
        raise ValueError('Positive precision and a declared slenderness criterion required')
    if len(faces)>500000:raise ValueError('Reviewed bar topology budget exceeded')
    observations=[];components=[]
    for index,(v,f) in enumerate(parts(vertices,faces)):
        if len(v)<4:continue
        center,basis,spans=planar_frame(v)
        rectangle=MultiPoint((v-center)@basis[1:].T).minimum_rotated_rectangle
        widths=[]
        if rectangle.geom_type=='Polygon':
            corners=np.asarray(rectangle.exterior.coords)[:4]
            widths=np.linalg.norm(np.roll(corners,-1,axis=0)-corners,axis=1)[:2].tolist()
        points,inverse=np.unique(v,axis=0,return_inverse=True);indexed=inverse[f]
        edges=np.sort(np.concatenate([indexed[:,[0,1]],indexed[:,[1,2]],indexed[:,[2,0]]]),axis=1)
        _,multiplicity=np.unique(edges,axis=0,return_counts=True)
        closed=bool(len(multiplicity) and np.all(multiplicity==2))
        tri=v[f]-center
        area=float(np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1).sum()/2)
        volume=abs(float(np.einsum('ij,ij->i',tri[:,0],np.cross(tri[:,1],tri[:,2])).sum()/6))
        ratio=float(spans[0]/max(widths)) if widths and max(widths)>0 else 0.
        qualifies=bool(closed and widths and min(widths)>10*precision_m
            and ratio>=minimum_length_width_ratio and volume>area*precision_m)
        row={'part_index':index,'vertices':len(v),'triangles':len(f),'center_m':center.tolist(),
            'principal_spans_m':spans.tolist(),'cross_section_widths_m':widths,
            'length_width_ratio':ratio,'closed_triangle_edges':closed,'surface_area_m2':area,
            'signed_shell_volume_absolute_m3':volume,'qualifies':qualifies}
        observations.append(row)
        if qualifies:components.append(row)
    return {'count':len(components),'components':components,'observations':observations,
        'parameters':{'precision_m':precision_m,'minimum_length_width_ratio':minimum_length_width_ratio},
        'registration':'none','candidate_names_or_mesh_object_count_used_as_answers':False,
        'scope':'Closed straight bar bodies within independently reviewed complete workpiece geometry; exact coincident copies count once'}
