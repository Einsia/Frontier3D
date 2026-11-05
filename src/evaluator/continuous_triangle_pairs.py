"""Conservative float64 separating-axis rejection before exact intersections."""
import numpy as np


def shared_vertex_only(vertices,left,right,epsilon_m=1e-9):
    """Prove disjoint projected angular cones at an exact shared vertex.

Projection cannot hide a genuine intersection: if the projected cones have
only their origin in common and both projected triangles are nondegenerate,
their only possible common 3D point is the shared vertex. Near-cone boundaries
remain in the expensive exact test.
"""
    v,a,b=np.asarray(vertices,float),np.asarray(left),np.asarray(right)
    equal=a[:,:,None]==b[:,None,:];shared=equal.any(2)
    selected=np.flatnonzero(shared.sum(1)==1);answer=np.zeros(len(a),bool)
    if not len(selected):return answer
    ai=shared[selected].argmax(1);bi=equal[selected].any(1).argmax(1)
    rows=np.arange(len(selected));origin=v[a[selected,ai]]
    av=np.stack([v[a[selected,(ai+i)%3]]-origin for i in (1,2)],axis=1)
    bv=np.stack([v[b[selected,(bi+i)%3]]-origin for i in (1,2)],axis=1)
    drop=np.abs(np.cross(av[:,0],av[:,1])).argmax(1)
    axes=np.asarray([[1,2],[0,2],[0,1]])[drop]
    av=np.take_along_axis(av,axes[:,None,:],axis=2);bv=np.take_along_axis(bv,axes[:,None,:],axis=2)
    cross=lambda x,y:x[:,0]*y[:,1]-x[:,1]*y[:,0]
    da,db=cross(av[:,0],av[:,1]),cross(bv[:,0],bv[:,1])
    valid=(np.abs(da)>8*epsilon_m*np.linalg.norm(av,axis=2).max(1))&(np.abs(db)>8*epsilon_m*np.linalg.norm(bv,axis=2).max(1))
    av[da<0]=av[da<0,::-1];bv[db<0]=bv[db<0,::-1]
    def inside(cone,point):
        slack=4*epsilon_m*np.maximum(np.linalg.norm(cone,axis=2).max(1),np.linalg.norm(point,axis=1))
        return (cross(cone[:,0],point)>=-slack)&(cross(point,cone[:,1])>=-slack)
    overlap=inside(av,bv[:,0])|inside(av,bv[:,1])|inside(bv,av[:,0])|inside(bv,av[:,1])
    answer[selected]=valid&~overlap
    return answer


def possible_intersections(left,right,epsilon_m=1e-9):
    a,b=np.asarray(left,float),np.asarray(right,float)
    if a.shape!=b.shape or a.ndim!=3 or a.shape[1:]!=(3,3) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Paired complete finite triangles required')
    if epsilon_m<=0 or not np.isfinite(epsilon_m):raise ValueError('Positive finite intersection precision required')
    if not len(a):return np.zeros(0,bool)
    ea=np.roll(a,-1,axis=1)-a;eb=np.roll(b,-1,axis=1)-b
    na=np.cross(ea[:,0],ea[:,1]);nb=np.cross(eb[:,0],eb[:,1])
    axes=[na,nb,*[np.cross(na,ea[:,i]) for i in range(3)],*[np.cross(nb,eb[:,i]) for i in range(3)],
          *[np.cross(ea[:,i],eb[:,j]) for i in range(3) for j in range(3)]]
    # A shared arithmetic origin reduces cancellation; it changes no relative
    # geometry. A wide numeric slack only retains extra pairs for exact tests.
    a0=a[:,0].copy();a=a-a0[:,None,:];b=b-a0[:,None,:]
    slack=4*epsilon_m+64*np.finfo(float).eps*max(1.,float(np.max(np.abs(a0))),float(np.max(np.abs(a))),float(np.max(np.abs(b))))
    remaining=np.arange(len(a));possible=np.ones(len(a),bool)
    for axis in axes:
        if not len(remaining):break
        direction=axis[remaining];norm=np.linalg.norm(direction,axis=1)
        pa=np.einsum('nij,nj->ni',a[remaining],direction);pb=np.einsum('nij,nj->ni',b[remaining],direction)
        separated=(norm>0)&((pa.max(1)<pb.min(1)-slack*norm)|(pb.max(1)<pa.min(1)-slack*norm))
        possible[remaining[separated]]=False;remaining=remaining[~separated]
    return possible
