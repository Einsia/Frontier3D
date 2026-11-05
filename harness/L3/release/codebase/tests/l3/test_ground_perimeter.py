import unittest
from unittest.mock import patch
import numpy as np
from harness.L3.MinecraftVillage.ground_perimeter import perimeter_probes,choose_ground,ground_hit

class GroundPerimeterTests(unittest.TestCase):
 def test_geometry_order_and_range(self):
  bindings={'entities':{'farm.crop01':{'approach_cm':[0,150,86]}}}
  with patch('harness.L3.MinecraftVillage.ground_perimeter.actor_vertices',return_value={'farm.crop01':np.array([[-50,-50,0],[50,50,100]])}):
   steps,options=perimeter_probes({},bindings,[('farm.crop01','approach_cm','crop')])
  self.assertEqual(len(steps),36)
  self.assertEqual(options['crop'][0]['position_cm'],[0.,160.,86])
  self.assertTrue(all(s['collision_channel']=='pawn' for s in steps))
  self.assertEqual(bindings['entities']['farm.crop01']['approach_cm'],[0,150,86])
 def test_first_valid_real_hit(self):
  opts=[{'name':'a','position_cm':[0,0,86]},{'name':'b','position_cm':[10,0,86]}]
  events={'a':{'accepted':True,'collision_channel':'pawn','blocked':False},
          'b':{'accepted':True,'collision_channel':'pawn','blocked':True,'normal':[0,0,1],'point_cm':[10,0,4]}}
  self.assertEqual(choose_ground(opts,events)['position_cm'],[10,0,92])
 def test_no_hit_not_success(self):
  self.assertIsNone(choose_ground([{'name':'a','position_cm':[0,0,86]}],{'a':{'accepted':True,'collision_channel':'pawn','blocked':False}}))
 def test_invalid_observer_never_candidate_failure(self):
  for event in [{'accepted':False},{'accepted':True,'collision_channel':'visibility'}]:
   with self.assertRaises(ValueError):ground_hit(event,True)
 def test_wrong_hit_position_rejected(self):
  with self.assertRaises(ValueError):
   choose_ground([{'name':'a','position_cm':[0,0,86]}],{'a':{'accepted':True,'collision_channel':'pawn','blocked':True,'normal':[0,0,1],'point_cm':[10,0,0]}})
 def test_doors_not_retargeted(self):
  with patch('harness.L3.MinecraftVillage.ground_perimeter.actor_vertices',return_value={}):
   self.assertEqual(perimeter_probes({}, {},[('house01.door','crossing_from_cm','door')]),([],{}))
