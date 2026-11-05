"""Declared rectangular cavities, open pin notches and internal floor probes."""
import numpy as np
from .continuous_assembly_features import quantity,selected_loop,FRACTIONS
from .continuous_numeric import line_intersections
from .l1_sections import axial_corridor


def rectangular_cavity(part,definition):
    cavity=definition['rectangular_cavity'];width,depth=cavity['size_m'];rows=[]
    spans=cavity['section_spans_offset_m']
    for offsets in spans:
        for fraction in FRACTIONS:
            z=part.center[2]+offsets[0]+fraction*(offsets[1]-offsets[0]);section=part.at(float(z))
            if section['status']=='technical_failure':rows.append(section);continue
            loop=selected_loop(section,part.center,kind='cavity')
            if loop is None:
                rows.append(quantity(None,[width,depth],{'section':section}));continue
            frame=np.asarray(section['raw']['basis_world']);uv=np.asarray(loop['points_m'])
            xyz=np.column_stack([uv,np.full(len(uv),section['raw']['offset_m'])])@frame.T
            xy=xyz[:,:2]-part.center[:2]
            # Four observed extrema and four public corners cover both size
            # and rectangular shape; a circular hole cannot pass this test.
            rows.append(quantity(np.r_[xy.min(0),xy.max(0)].tolist(),[-width/2,-depth/2,width/2,depth/2],{'section':section}))
            a=xy;b=np.roll(a,-1,axis=0);edge=b-a;length2=(edge*edge).sum(1)
            for corner in np.array([[-1,-1],[-1,1],[1,-1],[1,1]])*np.array([width,depth])/2:
                t=np.divide(((corner-a)*edge).sum(1),length2,out=np.zeros_like(length2),where=length2>0)
                distance=float(np.linalg.norm(corner-(a+np.clip(t,0,1)[:,None]*edge),axis=1).min())
                rows.append(quantity(distance,0.,{'public_corner_local_m':corner.tolist(),'section':section}))
    opening=[];lo,hi=cavity['clearance_span_offset_m'];lo+=part.center[2];hi+=part.center[2]
    # Fixed area samples cover the complete rectangular opening, including
    # corners outside its inscribed circle. Bounds are from the public task.
    for x in (np.arange(8)+.5)/8-.5:
        for y in (np.arange(8)+.5)/8-.5:
            origin=part.center.copy();origin[:2]+=np.array([x*width,y*depth]);origin[2]=0.
            hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,[0,0,1])
            obstacles=hits[(hits>=lo)&(hits<=hi)]
            opening.append(quantity(0. if not len(obstacles) else None,0.,
                {'origin_m':origin.tolist(),'intersections_m':hits.tolist(),'public_free_span_m':[lo,hi],
                 'blocking_intersections_m':obstacles.tolist()}))
    return {'rectangular_sections':rows,'rectangular_opening':opening}


def notch(part,definition,hole):
    axis=hole['axis'];axes=[i for i in range(3) if i!=axis]
    center=part.center+np.asarray(hole['center_m'])-np.asarray(definition['center_m']);rows=[]
    for span in hole['section_spans_offset_m']:
        for fraction in FRACTIONS:
            coordinate=part.center[axis]+span[0]+fraction*(span[1]-span[0])
            for angle in (np.arange(32)+.5)*np.pi/32:
                origin=center.copy();origin[axis]=coordinate;direction=np.zeros(3)
                direction[axes]=[np.cos(angle),np.sin(angle)]
                hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,direction)
                positive=hits[hits>1e-8]
                rows.append(quantity(None if not len(positive) else float(2*positive[0]),hole['diameter_m'],
                    {'origin_m':origin.tolist(),'direction':direction.tolist(),'intersections_m':hits.tolist()}))
    center[axis]=0.
    corridor=axial_corridor(part.mesh,center,np.eye(3)[axis],[float(part.low[axis]),float(part.high[axis])],hole['diameter_m']/2-.00015)
    radius=corridor['minimum_boundary_radius_m']
    rows.append(quantity(None if radius is None or radius<=1e-9 else max(0.,hole['diameter_m']-2*radius),0.,
                         {'full_triangle_corridor':corridor,'notch_half_plane':'positive second transverse axis'}))
    return rows


def line_boundaries(part,probe):
    origin=part.center+np.asarray(probe['origin_offset_m']);axis=probe['axis'];origin[axis]=0.
    hits=line_intersections(part.mesh.vertices,part.mesh.triangles,origin,np.eye(3)[axis])
    wanted=part.center[axis]+np.asarray(probe['boundary_offsets_m'])
    return quantity(hits.tolist() if len(hits)==len(wanted) else None,wanted.tolist(),
                    {'origin_m':origin.tolist(),'axis':axis,'intersections_m':hits.tolist(),'public_probe':probe})
