"""Numerical geometry measurements; role bindings do not establish semantics."""
import numpy as np

from .l2_metrics import entities,planar_dimensions,_inside
from .metrics import _register,MissingEvidence


def complete_members(members):
    if any(o.get('geometry_evidence',{}).get('status')=='sampled_surface' for _,o in members):
        raise MissingEvidence('Complete surface triangles required; dense diagnostic samples cannot prove a dimension')
    return members


@_register('l2_measured_route','road_role start_role goal_role min_width cell_size max_snap','clearance_height')
def measured_route(check,evidence,spec):
    from .l2_metrics import traversable_route
    complete_members([(n,o) for n,o in evidence['scene']['objects'].items() if o.get('visible_render')])
    return traversable_route(check,evidence,spec)


@_register('l2_role_planar_width','role expected tolerance')
def planar_width(check,evidence,spec):
    """The shorter side of the minimum-area planar box, per declared entity."""
    groups=entities(evidence,check.params['role'])
    if not groups:raise MissingEvidence('No geometry bound to '+check.params['role'])
    values=[]
    for group in groups:
        width=float(min(planar_dimensions(complete_members(group['members']))))
        values.append({'entity':group['id'],'width_m':width,
            'passed':abs(width-check.params['expected'])<=check.params['tolerance']})
    return float(all(v['passed'] for v in values)),{'entities':values,
        'selection':'Declared mattress footprint; not semantic classification'}


@_register('l2_role_planar_extent','role expected relative_tolerance')
def planar_extent(check,evidence,spec):
    selected=entities(evidence,check.params['role'])
    if not selected:raise MissingEvidence('No geometry bound to '+check.params['role'])
    members=[m for group in selected for m in group['members']]
    actual=np.asarray(planar_dimensions(complete_members(members)));expected=np.sort(check.params['expected'])
    relative=np.abs(actual-expected)/expected
    passed=bool(np.all(relative<=check.params['relative_tolerance']))
    return float(passed),{'dimensions_m':actual.tolist(),'expected_m':expected.tolist(),
        'relative_error':relative.tolist(),'selection':'Declared numerical role; not semantic classification'}


@_register('l2_role_height_above_support','role support_role expected tolerance')
def height_above_support(check,evidence,spec):
    groups=entities(evidence,check.params['role']);supports=entities(evidence,check.params['support_role'])
    if not groups or not supports:raise MissingEvidence('Numerical role and support geometry required')
    outcomes=[]
    for group in groups:
        xy=(group['low'][:2]+group['high'][:2])/2;hits=[]
        for support in supports:
            for _,obj in support['members']:
                if obj.get('geometry_evidence',{}).get('status')=='sampled_surface':
                    raise MissingEvidence('Height ray needs complete support triangles')
                for raw in obj.get('surface_triangles',[]):
                    tri=np.asarray(raw);normal=np.cross(tri[1]-tri[0],tri[2]-tri[0])
                    if abs(normal[2])>1e-12 and _inside(xy,tri):
                        z=float(tri[0,2]-np.dot(normal[:2],xy-tri[0,:2])/normal[2])
                        if z<=group['low'][2]+check.params['tolerance']:hits.append(z)
        if not hits:raise MissingEvidence('No local support surface beneath numerical role')
        height=float(group['high'][2]-max(hits))
        outcomes.append({'entity':group['id'],'height_m':height,
            'passed':abs(height-check.params['expected'])<=check.params['tolerance']})
    return float(all(v['passed'] for v in outcomes)),{'entities':outcomes,'reference':'Measured local support surface'}
