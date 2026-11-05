"""Public bolt and stepped rotary profiles measured on complete triangle meshes."""
import numpy as np
from .continuous_assembly_features import circular_rows,hexagon_rows,quantity
from .continuous_numeric import line_intersections


def bolt(part,definition):
    split=float(part.high[2]-definition['head_height_m'])
    rows={'shank_diameter':circular_rows(part,definition['shank_diameter_m'],span=(float(part.low[2]),split)),
          'hex_head':hexagon_rows(part,(split,float(part.high[2])),definition['head_diameter_m']),
          'shank_length':[],'head_height':[]}
    radius=(definition['shank_diameter_m']/2+definition['head_diameter_m']*np.sqrt(3)/4)/2
    for angle in np.arange(32)*2*np.pi/32:
        origin=np.array([part.center[0]+radius*np.cos(angle),part.center[1]+radius*np.sin(angle),0.])
        hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,[0,0,1])
        raw={'origin_m':origin.tolist(),'intersections_m':hits.tolist()}
        rows['shank_length'].append(quantity(None if len(hits)<2 else float(hits[0]-part.low[2]),definition['shank_length_m'],raw))
        rows['head_height'].append(quantity(None if len(hits)<2 else float(hits[-1]-hits[0]),definition['head_height_m'],raw))
    return rows


def stepped_rotary(part,definition):
    rows={};axis=definition['axis'];axes=[i for i in range(3) if i!=axis]
    for segment in definition['outer_profile']:
        span=part.center[axis]+np.asarray(segment['span_offset_m'])
        rows['profile/'+segment['id']]=circular_rows(part,segment['diameter_m'],axis=axis,span=span)
    for probe in definition['axial_profile_probes']:
        observations=[]
        for angle in np.arange(32)*2*np.pi/32:
            origin=part.center.copy();origin[axis]=0.
            origin[axes]+=probe['radius_m']*np.array([np.cos(angle),np.sin(angle)])
            hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,np.eye(3)[axis])
            expected=np.asarray(probe['boundary_offsets_m'])+part.center[axis]
            actual=hits.tolist() if len(hits)==len(expected) else None
            observations.append(quantity(actual,expected.tolist(),{'origin_m':origin.tolist(),'intersections_m':hits.tolist(),
                'public_profile_probe':probe}))
        rows['profile_edges/'+probe['id']]=observations
    return rows
