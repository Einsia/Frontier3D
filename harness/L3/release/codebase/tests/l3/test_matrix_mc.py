import json,tempfile,unittest,os
from pathlib import Path
from unittest.mock import patch
from tools.l3_matrix_mc import collect_runtime
from tools.l3_leaderboard_batch import write,read

class MCCollectionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
  self.trial=root/'trial';self.out=root/'result';self.out.mkdir()
  write(self.trial/'trial.json',{'model':'gpt-6-astra','reasoning_effort':'medium'})
  write(self.trial/'submission-manifest.json',{'files':{}})
  write(self.out/'verification/run.json',{'status':'collected','source_sha256':'source','verification_source_sha256':'verifier'})
 def tearDown(self):self.temp.cleanup()
 def test_runtime_finishes_before_collection_is_declared(self):
  calls=[]
  def execute(label,args,folder):
   calls.append(label)
   if label=='geometry':write(folder/'algorithms/geometry/geometry.json',{})
   if label=='capture':write(folder/'algorithms/capture/capture.json',{'status':'measured','episodes':{'workflow':{'status':'measured'}}})
   if label=='runtime':write(folder/'algorithms/runtime-geometry-v2/run.json',{'status':'measured'})
  with patch('tools.l3_matrix_mc.execute',execute),patch('tools.l3_matrix_mc.tree_digest',return_value='source'):
   collect_runtime(self.trial,self.out)
  self.assertEqual(calls,['geometry','capture','runtime'])
  self.assertEqual(read(self.out/'run.json')['status'],'collected')
  self.assertEqual(read(self.out/'source.json')['reasoning_effort'],'medium')
 def test_failed_runtime_not_reported_collected(self):
  def execute(label,args,folder):
   if label=='geometry':write(folder/'algorithms/geometry/geometry.json',{})
   if label=='capture':write(folder/'algorithms/capture/capture.json',{'status':'measured','episodes':{'workflow':{'status':'measured'}}})
   if label=='runtime':raise RuntimeError('replay failed')
  with patch('tools.l3_matrix_mc.execute',execute):
   with self.assertRaises(RuntimeError):collect_runtime(self.trial,self.out)
  self.assertFalse((self.out/'run.json').exists())
 def test_failed_capture_is_archived_and_retried(self):
  write(self.out/'algorithms/capture/capture.json',{'status':'failed'})
  old=self.out/'verification/workspace/algorithm-v1'
  old.mkdir(parents=True);(old/'evidence.txt').write_text('failed evidence')
  calls=[]
  def execute(label,args,folder):
   calls.append(label)
   if label=='geometry':write(folder/'algorithms/geometry/geometry.json',{})
   if label=='capture':
    self.assertFalse(old.exists())
    self.assertTrue(list(old.parent.glob('algorithm-v1-failed-*/evidence.txt')))
    write(folder/'algorithms/capture/capture.json',{'status':'measured','episodes':{}})
   if label=='runtime':write(folder/'algorithms/runtime-geometry-v2/run.json',{'status':'measured'})
  with patch('tools.l3_matrix_mc.execute',execute),patch('tools.l3_matrix_mc.tree_digest',return_value='source'):
   collect_runtime(self.trial,self.out)
  self.assertIn('capture',calls)
 def test_episode_infrastructure_failure_blocks_collection(self):
  def execute(label,args,folder):
   if label=='geometry':write(folder/'algorithms/geometry/geometry.json',{})
   if label=='capture':write(folder/'algorithms/capture/capture.json',{'status':'measured','episodes':{'workflow':{'status':'infrastructure_failure'}}})
  with patch('tools.l3_matrix_mc.execute',execute):
   with self.assertRaises(RuntimeError):collect_runtime(self.trial,self.out)
  self.assertFalse((self.out/'run.json').exists())
 def test_replay_budget_scales_without_modifying_plan(self):
  from tools.capture_l3_algorithms import replay_timeout
  plan={'steps':[{'op':'wait','seconds':400},{'op':'capture','name':'proof'}]}
  before=json.dumps(plan)
  self.assertEqual(replay_timeout(plan),5700)
  self.assertEqual(replay_timeout({'steps':[]}),3600)
  self.assertEqual(json.dumps(plan),before)
 def test_matrix_astra_uses_its_own_mc_report(self):
  from harness.L3.Suite.physical_batch_v2 import inputs
  root=Path(self.temp.name)/'matrix'
  write(root/'l3-g01/summary.json',{'source':{}})
  write(root/'l3-g01/algorithms/report.json',{'verification':str(root/'l3-g01/verification')})
  with patch.dict(os.environ,{'L3_EVAL_OUT':str(root)}):
   geometry,roles,episodes,summary=inputs('l3-g01','astra')
  self.assertEqual(geometry,root/'l3-g01/algorithms/geometry')
  self.assertEqual(episodes,root/'l3-g01/verification/workspace/episodes')
  self.assertTrue(roles)

if __name__=='__main__':unittest.main()

def test_mc_child_measurement_uses_active_python_environment(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    import tools.l3_matrix_mc as module
    calls=[]
    monkeypatch.setattr(module.subprocess,'run',lambda cmd,**kwargs:(calls.append((cmd,kwargs)) or SimpleNamespace(returncode=0)))
    module.execute('fixture',['-m','harness.L3.MinecraftVillage.algorithm_geometry'],tmp_path)
    assert calls[0][0][0]==sys.executable
    assert calls[0][0][1:]==['-m','harness.L3.MinecraftVillage.algorithm_geometry']
