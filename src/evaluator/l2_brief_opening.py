"""Interior aperture dimensions and bounded passage probes, without hidden GT."""
import numpy as np

from .l2_brief_numeric import floor_at,interval
from .l2_reference_numeric import groups,triangles,ray_distances
from .metrics import MissingEvidence,_register


@_register('l2_brief_opening','role support_role min_width min_height passage_shape relative_tolerance')
def opening(check,evidence,spec):
    p=check.params;support=np.concatenate([s for _,s in groups(evidence,p['support_role'])])
    all_surface=np.concatenate([triangles(o,evidence) for o in evidence['scene']['objects'].values()
        if o.get('type')=='MESH' and o.get('visible_render') and o.get('faces')])
    rows=[]
    for group,surface in groups(evidence,p['role']):
        points=surface.reshape(-1,3);xy=points[:,:2];centered=xy-xy.mean(axis=0)
        _,axes=np.linalg.eigh(centered.T@centered)
        width_axis=np.array([*axes[:,-1],0.]);depth_axis=np.cross([0,0,1],width_axis)
        projected=np.column_stack((points@width_axis,points@depth_axis))
        mid=(projected.min(axis=0)+projected.max(axis=0))/2
        center=mid[0]*width_axis+mid[1]*depth_axis
        ground=floor_at(support,center[:2],float(points[:,2].min())+1e-4)
        center[2]=ground+1e-5
        above=ray_distances(surface,center,[0,0,1])
        if not len(above):raise MissingEvidence('No actual lintel/arch surface over the selected opening')
        height=float(above[0]+1e-5)
        # Width at the low opening section; a natural arch span is not its
        # narrowing mid-height chord or its external bounding box.
        side_point=center.copy();side_point[2]=ground+min(height*.01,.01)
        left=ray_distances(surface,side_point,-width_axis);right=ray_distances(surface,side_point,width_axis)
        if not len(left) or not len(right):raise MissingEvidence('Both interior side boundaries are required')
        width=float(left[0]+right[0]);depth=float(np.ptp(projected[:,1]))
        clear=True;probes=0
        probe_height=p['min_height'] if p['min_height'] is not None else height*.5
        probe_width=p['min_width'];tolerance=p['relative_tolerance']
        for x in np.linspace(-.5,.5,11)*probe_width*(1-tolerance):
            for z in np.linspace(.01,.99,11)*probe_height*(1-tolerance):
                if p['passage_shape']=='ball':
                    radius=probe_width*(1-tolerance)/2
                    if x*x+(z-radius)**2>radius*radius:continue
                start=center+width_axis*x-depth_axis*(depth/2+1e-4);start[2]=ground+z
                hits=ray_distances(all_surface,start,depth_axis);probes+=1
                if len(hits) and hits[0]<depth+2e-4:clear=False
        valid=interval(width,p['min_width'],None,tolerance) and interval(height,p['min_height'],None,tolerance) and clear
        rows.append({'entity':group['id'],'interior_width_m':width,'interior_height_m':height,
            'passage_probes':probes,'sampled_passage_clear':clear,'passed':valid})
    return float(all(r['passed'] for r in rows)),{'entities':rows,
        'scope':'Interior dimensions and at most 121 through-depth rays; ball cross-section uses disk probes. Not a continuous-volume collision proof.'}
