"""World-space solid overlap by fixed stratified rays and interval integration.

The transverse samples are deterministic Sobol points. Every ray is intersected
with all potentially intersecting triangles in float64; parity defines the
occupied intervals independently of inconsistent face normals. Overlap lengths
are integrated exactly along each sampled ray. This is a sampled volume
estimate, not a certificate that arbitrarily small overlaps are absent.
"""
import numpy as np
from scipy.stats import qmc
from .continuous_surface import triangle_areas

POLICY={'rays':32768,'random_seed':20261016,'merge_m':1e-9,
        'method':'sobol_transverse_rays_half_open_faces_parity_v4','registration':'none',
        'coincident_crossings':'retain odd multiplicity after half-open triangle ownership',
        'barycentric_boundary_precision':0.}


class RayIntervals:
    def __init__(self,vertices,triangles,axis,*,merge_m=1e-9):
        self.vertices=np.asarray(vertices,float);self.triangles=np.asarray(triangles)
        triangle_areas(self.vertices,self.triangles)
        if axis not in (0,1,2) or not np.isfinite(merge_m) or merge_m<=0:raise ValueError('Invalid ray policy')
        self.axis=axis;self.axes=[i for i in range(3) if i!=axis];self.merge=merge_m
        self.xyz=self.vertices[self.triangles].copy();self.xy=self.xyz[:,:,self.axes]
        # Canonical projected winding gives each shared triangle edge exactly
        # one owner, independently of the scene's face-normal consistency.
        e1=self.xy[:,1]-self.xy[:,0];e2=self.xy[:,2]-self.xy[:,0]
        reverse=e1[:,0]*e2[:,1]-e1[:,1]*e2[:,0]<0
        self.xyz[reverse]=self.xyz[reverse][:,[0,2,1]];self.xy=self.xyz[:,:,self.axes]
        a,b,c=(self.xy[:,i] for i in range(3))
        self.edge1=b-a;self.edge2=c-a
        self.det=self.edge1[:,0]*self.edge2[:,1]-self.edge1[:,1]*self.edge2[:,0]
        def owned(edge):
            return (edge[:,1]>0)|((edge[:,1]==0)&(edge[:,0]<0))
        self.owns_u=owned(a-c);self.owns_v=owned(b-a);self.owns_w=owned(c-b)
        self.low=self.xy.min(1);self.high=self.xy.max(1);centres=(self.low+self.high)/2
        self.nodes=[]
        def build(ids):
            index=len(self.nodes);self.nodes.append(None)
            low,high=self.low[ids].min(0),self.high[ids].max(0)
            if len(ids)<=24:self.nodes[index]=(low,high,None,None,ids)
            else:
                split=np.ptp(centres[ids],axis=0).argmax();mid=len(ids)//2
                order=np.argpartition(centres[ids,split],mid)
                left,right=build(ids[order[:mid]]),build(ids[order[mid:]])
                self.nodes[index]=(low,high,left,right,None)
            return index
        usable=np.flatnonzero(self.det!=0)
        if len(usable):build(usable)

    def intervals(self,points):
        points=np.asarray(points,float)
        if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all():raise ValueError('Finite transverse points required')
        pending=[(0,np.arange(len(points)))] if self.nodes else [];records=[];evaluated=0
        while pending:
            index,ids=pending.pop();low,high,left,right,faces=self.nodes[index]
            ids=ids[((points[ids]>=low-self.merge)&(points[ids]<=high+self.merge)).all(1)]
            if not len(ids):continue
            if faces is None:pending.extend(((left,ids),(right,ids)));continue
            for start in range(0,len(ids),2048):
                subset=ids[start:start+2048];delta=points[subset,None,:]-self.xy[faces,0]
                u=(delta[:,:,0]*self.edge2[faces,1]-delta[:,:,1]*self.edge2[faces,0])/self.det[faces]
                v=(self.edge1[faces,0]*delta[:,:,1]-self.edge1[faces,1]*delta[:,:,0])/self.det[faces]
                w=1-u-v;eps=POLICY['barycentric_boundary_precision']
                keep=((u>eps)|((np.abs(u)<=eps)&self.owns_u[faces]))&\
                     ((v>eps)|((np.abs(v)<=eps)&self.owns_v[faces]))&\
                     ((w>eps)|((np.abs(w)<=eps)&self.owns_w[faces]))
                rows,columns=np.nonzero(keep);evaluated+=len(subset)*len(faces)
                if not len(rows):continue
                z=self.xyz[faces,:,self.axis]
                hits=z[columns,0]+u[rows,columns]*(z[columns,1]-z[columns,0])+v[rows,columns]*(z[columns,2]-z[columns,0])
                records.append((subset[rows],hits))
        result=[[] for _ in points]
        if records:
            ids=np.concatenate([r[0] for r in records]);hits=np.concatenate([r[1] for r in records])
            order=np.lexsort((hits,ids));ids,hits=ids[order],hits[order]
            distinct=np.r_[True,(ids[1:]!=ids[:-1])|(hits[1:]-hits[:-1]>self.merge)]
            starts=np.flatnonzero(distinct);counts=np.diff(np.r_[starts,len(ids)])
            # Two coincident boundaries cancel in even-odd occupancy. Simply
            # deduplicating would turn two touching closed components into an
            # apparently open solid. Half-open ownership already removed the
            # duplicate hits due to triangulation of a single surface.
            starts=starts[counts%2==1];ids,hits=ids[starts],hits[starts]
            if len(ids):
                starts=np.r_[0,1+np.flatnonzero(ids[1:]!=ids[:-1]),len(ids)]
                for start,end in zip(starts[:-1],starts[1:]):result[int(ids[start])]=hits[start:end].tolist()
        odd=[i for i,hits in enumerate(result) if len(hits)%2]
        return result,{'rays':len(points),'triangle_ray_tests':evaluated,'odd_crossing_rays':odd,
                       'normal_policy':'orientation_independent_even_odd_boundary_parity',
                       'triangle_boundary_policy':'half_open_projected_edges',
                       'coincident_boundary_policy':'odd_multiplicity'}


def interval_overlap(left,right,low,high):
    i=j=0;total=0.
    while i+1<len(left) and j+1<len(right):
        a=max(left[i],right[j],low);b=min(left[i+1],right[j+1],high)
        total+=max(0.,b-a)
        if left[i+1]<=right[j+1]:i+=2
        else:j+=2
    return total


def overlap_volume(left,right,*,rays=32768,seed=20261016,merge_m=1e-9):
    if type(rays) is not int or rays<16 or rays&(rays-1):raise ValueError('Power-of-two ray population required')
    populations=[]
    for v,f in (left,right):
        areas=triangle_areas(v,f);v=np.asarray(v,float);f=np.asarray(f)
        if not len(areas) or areas.sum()<=0:return {'status':'absent','reason':'Required solid surface absent'}
        populations.append((v,f,float(areas.sum())))
    low=np.maximum(populations[0][0].min(0),populations[1][0].min(0))
    high=np.minimum(populations[0][0].max(0),populations[1][0].max(0));span=high-low
    common={'coordinate_space':'world_metres','registration':'none','policy':{**POLICY,'rays':rays,'random_seed':seed,'merge_m':merge_m},
            'left_area_m2':populations[0][2],'right_area_m2':populations[1][2],
            'overlap_bounds_m':[low.tolist(),high.tolist()]}
    if np.any(span<=merge_m):
        return {**common,'status':'measured','intersection_volume_m3':0.,'sampling':'disjoint_or_contact_within_numeric_precision',
                'sampled_rays':0,'unresolved_thickness_bound_m':max(0.,float(span.min()))}
    axis=int(np.argmax(span));axes=[i for i in range(3) if i!=axis]
    samples=qmc.Sobol(2,scramble=True,seed=seed).random_base2(rays.bit_length()-1)
    points=low[axes]+samples*span[axes];observations=[];intervals=[]
    for v,f,_ in populations:
        values,observed=RayIntervals(v,f,axis,merge_m=merge_m).intervals(points)
        observations.append(observed);intervals.append(values)
    odd=set(observations[0]['odd_crossing_rays'])|set(observations[1]['odd_crossing_rays'])
    lengths=np.array([interval_overlap(a,b,float(low[axis]),float(high[axis])) if i not in odd else 0.
                      for i,(a,b) in enumerate(zip(*intervals))])
    area=float(np.prod(span[axes]));volume=float(area*lengths.mean())
    return {**common,'status':'unresolved_crossings' if odd else 'measured',
            'reason':'Open or ambiguous boundary crossings observed' if odd else None,
            'intersection_volume_m3':None if odd else volume,'axis':axis,'transverse_area_m2':area,
            'observations':observations,'sampled_rays':rays,'overlap_lengths_m':lengths.tolist(),
            'transverse_points_m':points.tolist(),'invalid_ray_fraction':len(odd)/rays,
            'half_population_estimates_m3':[float(area*x.mean()) for x in np.array_split(lengths,2)],
            'sampling':'finite_transverse_samples_full_triangle_axial_intersections',
            'limitation':'Finite transverse samples can miss overlaps with very small projected area.'}
