import unittest,types,sys
from unittest.mock import patch,MagicMock
from harness.L3.MinecraftVillage.scene_geometry import Scene
class TopologyGuardTests(unittest.TestCase):
 def test_open_mesh_never_enters_native_constructor(self):
  mesh={'vertices_cm':[[0,0,0],[100,0,0],[0,100,0]],'indices':[0,1,2]}
  item={'actor':'sheet','component':'mesh','mesh':'open','axis_x':[1,0,0],'axis_y':[0,1,0],'axis_z':[0,0,1],'origin_cm':[0,0,0]}
  scene=Scene({'meshes':{'open':mesh},'instances':[item]},open_surface_fallback=True)
  native=types.SimpleNamespace(Mesh64=MagicMock())
  with patch.dict(sys.modules,{'manifold3d':native}):
   with self.assertRaisesRegex(ValueError,'Not a closed valid solid'):scene.solid(0)
  native.Mesh64.assert_not_called()
if __name__=='__main__':unittest.main()
