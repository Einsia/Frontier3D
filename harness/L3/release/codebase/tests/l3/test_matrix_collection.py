import unittest
from pathlib import Path
from tools.l3_matrix_collection import collect_slot
class Slots(unittest.TestCase):
 def test_resolves_recorded_engine(self):
  engines={0:Path('/tmp/eval-slot-00'),1:Path('/tmp/eval-slot-01')}
  self.assertEqual(collect_slot('/tmp/eval-slot-01',engines),1)
  self.assertIsNone(collect_slot('/tmp/generation-slot-01',engines))
if __name__=='__main__':unittest.main()

class JudgeRouting(unittest.TestCase):
 def test_collection_routes_translation_to_host_judge(self):
  from unittest.mock import patch
  import os
  from tools.l3_matrix_collection import collection_environment
  from harness.L3.Suite.vlm import call
  env=collection_environment({'model':'kimi-k3','effort':'max'},Path('/tmp/trial'),Path('/tmp/out'))
  self.assertEqual(env['L3_MODEL_GROUP'],'openai')
  with patch.dict(os.environ,env), patch('harness.L3.Suite.matrix_judge.call',return_value={'route':1}) as host, patch('harness.L3.Suite.vlm.build_codex_command') as docker:
   self.assertEqual(call(Path('/tmp/packet'),'prompt',[],{}),{'route':1})
   host.assert_called_once()
   docker.assert_not_called()
