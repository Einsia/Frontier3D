import numpy as np
from harness.L3.Suite.open_surface import crossing

def test_distant_triangles_do_not_change_crossings():
    left=np.array([[[-5.,-5.,0.],[5.,-5.,0.],[0.,5.,0.]]])
    right=np.array([[[0.,-4.,-5.],[0.,4.,-5.],[0.,0.,5.]]])
    expected=crossing(left,right,0.1)
    assert expected['violates']
    distant=np.repeat(right+10000,1000,axis=0)
    assert crossing(left,np.concatenate([distant,right,distant]),0.1)==expected

def test_disjoint_meshes_preserve_empty_crossing_result():
    tri=np.array([[[0.,0.,0.],[10.,0.,0.],[0.,10.,0.]]])
    result=crossing(tri,tri+100,2.)
    assert result['violates'] is False and result['tested_crossing_pairs']==0

def test_touching_aabb_stays_nonpenetrating():
    tri=np.array([[[0.,0.,0.],[10.,0.,0.],[0.,10.,0.]]])
    assert crossing(tri,tri,0.)['violates'] is False
