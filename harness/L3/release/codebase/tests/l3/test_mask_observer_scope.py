import unittest
from tools.refresh_l3_mask_observer import nonmask_source
class MaskScopeTests(unittest.TestCase):
 def test_material_scope_changes_do_not_change_nonmask_source(self):
  original='#include "Components/StaticMeshComponent.h"\n    if(Op==TEXT("instance_masks")) { old; }\n    if(Op==TEXT("ray")) { stable; }'
  updated=original.replace('    if(Op==TEXT("instance_masks")) { old; }','    if(Op==TEXT("instance_masks")) { new; }')
  updated='#include "Components/MeshComponent.h"\n'+updated
  self.assertEqual(nonmask_source(original),nonmask_source(updated))
 def test_nonmask_behavior_change_is_detected(self):
  original='    if(Op==TEXT("instance_masks")) {}\n    if(Op==TEXT("ray")) { stable; }'
  self.assertNotEqual(nonmask_source(original),nonmask_source(original.replace('stable','changed')))
if __name__=='__main__':unittest.main()
