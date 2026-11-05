import copy,unittest,tomllib
from pathlib import Path
from tools.migrate_l3_sol61 import replacement,OLD,NEW
from tools.l3_leaderboard_batch import read,B
from tools.publish_l3_matrix_scores import retire_pending_variants
from tools.prepare_l3_trial import codex_config

class MigrationTest(unittest.TestCase):
 def test_matrix_preserves_other_models_and_no_reuse(self):
  before=read(B/'manifest.json')
  # Load the archived original on reruns.
  if not any(r['model']==OLD for r in before['rows']):
   before=read(Path(read(B/'sol61-migration.json')['archive'])/'manifest-before.json')
  original=copy.deepcopy(before);after,old=replacement(before)
  self.assertEqual(before,original)
  self.assertEqual(len(old),60);self.assertEqual(len(after['rows']),360)
  self.assertEqual([r for r in before['rows'] if r['model']!=OLD],
                   [r for r in after['rows'] if r['model']!=NEW])
  fresh=[r for r in after['rows'] if r['model']==NEW]
  self.assertEqual(len(fresh),60)
  self.assertTrue(all(r['status']=='queued' and r['reuse_source'] is None for r in fresh))
  self.assertTrue(all(NEW in r['output'] and NEW in r['id'] for r in fresh))
  self.assertEqual(sum(r['status']=='reused' for r in after['rows']),30)
  repeated,retired=replacement(after)
  self.assertEqual(repeated,after);self.assertEqual(retired,[])
 def test_board_retains_scores_and_other_levels(self):
  ids=[OLD,OLD+'--medium',OLD+'--xhigh',NEW+'--high']
  d={'models':[{'id':i,'base_model':i.split('--')[0]} for i in ids],
     'tasks':[{'key':'l3-g01','level':3,'model_results':[
       {'model_id':OLD,'status':'scored','report':{'score':.7}},
       {'model_id':OLD+'--medium','status':'scored','report':{'score':.5}},
       {'model_id':OLD+'--xhigh','status':'pending'},
       {'model_id':NEW+'--high','status':'pending'}]},
       {'key':'l1','level':1,'model_results':[{'model_id':OLD,'status':'scored'}]}]}
  original=copy.deepcopy(d)
  self.assertEqual(retire_pending_variants(d,[OLD]),[('l3-g01',OLD+'--xhigh')])
  self.assertEqual(d['tasks'][1],original['tasks'][1])
  self.assertEqual(d['tasks'][0]['model_results'][:2],original['tasks'][0]['model_results'][:2])
  self.assertIn(NEW+'--high',[r['model_id'] for r in d['tasks'][0]['model_results']])
 def test_native_config_exact_model_efforts(self):
  for e in ['medium','high','xhigh','max']:
   cfg=tomllib.loads(codex_config(NEW,e))
   self.assertEqual(cfg['model'],NEW);self.assertEqual(cfg['model_reasoning_effort'],e)
   self.assertFalse(cfg['features']['multi_agent'])
   self.assertEqual(cfg['web_search'],'disabled')
if __name__=='__main__':unittest.main()
