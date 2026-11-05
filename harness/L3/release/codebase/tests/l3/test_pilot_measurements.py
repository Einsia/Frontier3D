import unittest
import numpy as np
from harness.L3.MinecraftVillage.contact import contact
from harness.L3.MinecraftVillage.penetration import yaw_box_depth,box_template
from harness.L3.MinecraftVillage.rubric import validate_verdict
from src.evaluator.l2_support_chain import Surface,ContactBudget,contact as original_contact

class PilotMeasurements(unittest.TestCase):
 def test_conservative_filter_matches_l2_predicate(self):
  rng=np.random.default_rng(7203)
  for offset in [0,.005,.02,.021,.5,3]:
   for repeat in range(12):
    left=Surface(rng.uniform(-1,1,(4,3,3)));right=Surface(rng.uniform(-1,1,(5,3,3))+[offset,0,0])
    self.assertEqual(contact(left,right,.02,ContactBudget()),original_contact(left,right,.02,ContactBudget()))
 def test_disjoint_surfaces_with_overlapping_bounds(self):
  a=Surface(np.array([[[0.,0,0],[1,0,0],[0,1,0]]]))
  b=Surface(np.array([[[.8,.8,0],[1,.8,0],[.8,1,0]]]))
  self.assertFalse(contact(a,b,.02,ContactBudget()))
 def test_separation_contact_and_penetration(self):
  depths=yaw_box_depth(np.zeros(3),np.ones(3),0,np.array([[3,0,0],[2,0,0],[1.5,0,0]]),np.ones((3,3)))
  np.testing.assert_allclose(depths,[-1,0,.5])
 def test_sat_rejects_rotated_aabb_false_positive(self):
  depth=yaw_box_depth(np.zeros(3),np.array([2,.1,1]),45,np.array([[1.3,-1.3,0]]),np.array([[.1,.1,.1]]))
  self.assertLess(depth[0],0)
 def test_incomplete_cube_rejected(self):
  with self.assertRaises(ValueError):box_template({'vertices_cm':[[0,0,0],[1,1,1]],'indices':[0,1,0]})
 def test_major_defect_cannot_get_high_grade(self):
  v=dict(not_judgeable=False,score=3,discrepancy_severity='major',achieved='recognizable',discrepancies='missing structure')
  with self.assertRaises(ValueError):validate_verdict(v)
  v['score']=2;validate_verdict(v)
 def test_technical_failure_is_not_zero(self):
  with self.assertRaises(ValueError):validate_verdict(dict(not_judgeable=True,score=0))
  validate_verdict(dict(not_judgeable=True,score=None))

if __name__=='__main__':unittest.main()
