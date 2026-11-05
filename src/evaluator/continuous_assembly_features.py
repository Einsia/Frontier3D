"""Measured mechanical sections for public assembly requirements.

All points remain in world metres. A part's section centre is an observed
feature datum, never a fitted transform of the candidate scene. Section and
corridor records retain the actual polygon and complete-triangle observations.
"""
import numpy as np
from shapely.geometry import Polygon
from .continuous_numeric import scalar_error
from .l1_sections import section_loops, circle_boundary, axial_corridor
from .l1_surface import SurfaceMesh

FRACTIONS=(.125,.375,.625,.875)
TOLERANCE=.0003


def quantity(actual,expected,observation,*,tolerance=TOLERANCE,half_scale=None):
    if actual is None:
        return {'status':'absent','reason':'Required geometric feature not observed','observation':observation}
    return {'status':'measured','actual':actual,'expected':expected,'tolerance':tolerance,
            'normalized_errors':scalar_error(actual,expected,tolerance,half_scale),'observation':observation}


def section(mesh,height,axis=2):
    direction=np.eye(3)[axis]
    raw=section_loops(mesh,[0.,0.,0.],direction,float(height))
    if raw['status']!='ok':
        # A malformed boundary is an observed geometric defect. Numerical
        # inability to choose a section is a collector precision failure.
        if raw.get('reason')=='No nondegenerate nearby section plane':
            return {'status':'technical_failure','reason':raw['reason'],'raw':raw}
        return {'status':'absent','reason':raw['reason'],'raw':raw}
    loops=[]
    for loop in raw['loops']:
        points=np.asarray(loop['points_m']);polygon=Polygon(points)
        if not polygon.is_valid or polygon.area<=0:
            return {'status':'absent','reason':'Invalid observed section polygon','raw':raw}
        fit=circle_boundary(points)
        frame=np.asarray(raw['basis_world']);center=frame@np.r_[fit['center_plane_m'],raw['offset_m']]
        loops.append({**loop,**fit,'center_world_m':center.tolist(),'area_m2':polygon.area})
    # Geometric containment identifies cavity boundaries independently of
    # winding direction; wrongly oriented faces are scored by solid validity.
    for i,loop in enumerate(loops):
        polygon=Polygon(loop['points_m'])
        depth=sum(Polygon(other['points_m']).contains(polygon) for j,other in enumerate(loops) if j!=i)
        loop['containment_depth']=depth;loop['kind']='outer' if depth%2==0 else 'cavity'
    return {'status':'measured','loops':loops,'raw':raw}


class Part:
    def __init__(self,vertices,triangles,metadata=None):
        self.mesh=SurfaceMesh(vertices,triangles,surface_only=True)
        self.metadata=metadata or {}
        used=self.mesh.vertices[np.unique(self.mesh.triangles)]
        self.low,self.high=used.min(0),used.max(0)
        self.center=(self.low+self.high)/2
        self.sections={}

    def at(self,height,axis=2):
        key=(axis,float(height))
        if key not in self.sections:self.sections[key]=section(self.mesh,height,axis)
        return self.sections[key]

    def axial_sections(self,axis=2,span=None):
        lo,hi=span if span is not None else (self.low[axis],self.high[axis])
        return [self.at(lo+(hi-lo)*fraction,axis) for fraction in FRACTIONS]


def selected_loop(raw,center=None,*,kind='outer'):
    if raw['status']!='measured':return None
    loops=[r for r in raw['loops'] if r['kind']==kind]
    if not loops:return None
    return max(loops,key=lambda r:r['area_m2']) if center is None else min(
        loops,key=lambda r:np.linalg.norm(np.asarray(r['center_world_m'])-center))


def circular_rows(part,diameter,*,axis=2,span=None,kind='outer',center=None):
    rows=[]
    for raw in part.axial_sections(axis,span):
        if raw['status']=='technical_failure':rows.append(raw);continue
        local=None if center is None else np.asarray(center).copy()
        if local is not None:local[axis]=raw.get('raw',{}).get('offset_m',0.)
        loop=selected_loop(raw,local,kind=kind)
        actual=None if loop is None else [2*loop['min_boundary_radius_m'],2*loop['max_boundary_radius_m']]
        rows.append(quantity(actual,[diameter,diameter],{'section':raw,'selected_boundary':loop}))
    return rows


def bore_rows(part,center,diameter,*,axis=2,span=None):
    lo,hi=span if span is not None else (part.low[axis],part.high[axis])
    center=np.asarray(center,float).copy();center[axis]=0.
    rows=circular_rows(part,diameter,axis=axis,span=(lo,hi),kind='cavity',center=center)
    # Each section must contain the requested corridor axis. A different hole
    # cannot supply a matching radius for an absent public bore.
    for row in rows:
        if row['status']!='measured':continue
        boundary=row['observation']['selected_boundary'];raw=row['observation']['section']['raw']
        local=center@np.asarray(raw['basis_world'])[:,:2]
        from shapely.geometry import Point
        if not Polygon(boundary['points_m']).contains(Point(local)):
            row.update(status='absent',reason='Declared bore axis is outside the observed cavity')
        else:
            delta=np.asarray(boundary['center_world_m'])-center;delta[axis]=0.
            row['normalized_errors']+=scalar_error(float(np.linalg.norm(delta)),0.,TOLERANCE)
    radius=diameter/2
    corridor=axial_corridor(part.mesh,center,np.eye(3)[axis],[float(lo),float(hi)],max(radius-TOLERANCE/2,1e-8))
    minimum=corridor['minimum_boundary_radius_m']
    has_cavity=all(r['status']=='measured' for r in rows)
    opening=None if not has_cavity or minimum is None or minimum<=1e-9 else 2*minimum
    # Minimum opening is one-sided: extra aperture is penalized by section
    # diameters above; a cap or intrusion reduces the complete corridor term.
    rows.append(quantity(None if opening is None else max(0.,diameter-opening),0.,
                         {'full_triangle_corridor':corridor,'cavity_sections_observed':has_cavity}))
    return rows


def hexagon_rows(part,span,diameter,axis=2):
    rows=[]
    for raw in part.axial_sections(axis,span):
        if raw['status']=='technical_failure':rows.append(raw);continue
        loop=selected_loop(raw)
        if loop is None:
            rows.append(quantity(None,diameter,{'section':raw}));continue
        polygon=Polygon(loop['points_m']);simplified=polygon.simplify(1e-8,preserve_topology=True)
        points=np.asarray(simplified.exterior.coords)[:-1]
        vectors=np.roll(points,-1,axis=0)-points;lengths=np.linalg.norm(vectors,axis=1)
        center=np.asarray(loop['center_plane_m']);radii=np.linalg.norm(points-center,axis=1)
        corners=np.arccos(np.clip(np.einsum('ij,ij->i',-np.roll(vectors,1,axis=0),vectors)/
                                  (np.roll(lengths,1)*lengths),-1,1))
        observation={'section':raw,'simplified_vertices':points.tolist(),'corner_radians':corners.tolist()}
        # Independent count, circumradius, straight-side length and turn angles
        # prevent a circular or many-sided head from receiving a hex score.
        rows.extend([quantity(len(points),6,observation,tolerance=0.,half_scale=1.),
            quantity((2*radii).tolist(),[diameter]*len(radii),observation),
            quantity(lengths.tolist(),[diameter/2]*len(lengths),observation),
            quantity((corners*diameter/2).tolist(),[np.pi/3*diameter]*len(corners),observation)])
    return rows
