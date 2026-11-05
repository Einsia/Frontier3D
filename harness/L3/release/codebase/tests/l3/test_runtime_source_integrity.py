import tempfile,unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from tools import repair_l3_runtime as m

class RuntimeSourceIntegrity(unittest.TestCase):
 def replay(self,changed=False):
  with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
   root=Path(temp);trial=root/'trial';run=root/'run';output=root/'output'
   (run/'workspace').mkdir(parents=True)
   record={'source_sha256':'candidate-hash','verification_source_sha256':'verifier-hash','container':'trial-container',
           'command':['type=bind,src=/data/engines/slot-00,dst=/engine']}
   stack.enter_context(patch('tools.l3_ground_query.prepare_ground_observer',return_value=False))
   stack.enter_context(patch.object(m,'read_json',side_effect=lambda p:record if p==run/'run.json' else {}))
   stack.enter_context(patch.object(m,'tree_digest',side_effect=['candidate-hash','verifier-hash','changed' if changed else 'candidate-hash','verifier-hash']))
   stack.enter_context(patch.object(m,'load_geometry',return_value=(root/'geometry',{})))
   stack.enter_context(patch.object(m,'digest',return_value='hash'))
   stack.enter_context(patch.object(m,'derive_bindings',return_value=({'entities':{}},{})))
   engine=stack.enter_context(patch('tools.prepare_l3_trial.assert_engine_available'))
   stack.enter_context(patch.object(m,'reusable_episode',return_value=True))
   stack.enter_context(patch.object(m.subprocess,'run'))
   for name,value in [('make_workflow',({},{})),('door_walk_plan',({},{})),('diagnose',{}),('diagnose_doors',{}),('resource_plan',{}),('resource_diagnose',{}),('Scene',None),('motion_measure',{})]:
    stack.enter_context(patch.object(m,name,return_value=value))
   stack.enter_context(patch.object(m,'REQUIRED',[]))
   if changed:
    with self.assertRaisesRegex(ValueError,'Source changed'):m.repair(trial,run,output)
   else:
    m.repair(trial,run,output)
    import json
    self.assertEqual(json.loads((output/'run.json').read_text())['status'],'measured')
   engine.assert_called_once_with(Path('/data/engines/slot-00'))
 def test_engine_check_preserves_candidate_hash(self):self.replay()
 def test_real_candidate_change_is_rejected(self):self.replay(changed=True)

if __name__=='__main__':unittest.main()
