import copy,unittest
from tools.prioritize_l3_max import select,TARGETS
from tools.l3_leaderboard_batch import B,read,row_enabled
from tools.publish_l3_matrix_scores import schedule_variants
class PriorityTest(unittest.TestCase):
 def test_scope_harness_and_preservation(self):
  m=read(B/'manifest.json');old=copy.deepcopy(m);n,retired=select(m)
  self.assertEqual(m,old);self.assertEqual(sum(row_enabled(r) for r in n['rows']),165)
  self.assertEqual(sum(not row_enabled(r) for r in n['rows']),240)
  for r in n['rows']:
   if r['enabled']:self.assertEqual((r['effort'],r['harness']),TARGETS[r['model']])
   if r['model']=='qwen3.8-max' and r['effort']=='xhigh':
    self.assertEqual(r['harness'],'claude');self.assertIn('--claude',r['output']);self.assertIsNone(r['reuse_source'])
  a,_=select(n);self.assertEqual(a['rows'],n['rows'])
 def test_gateway_does_not_negotiate_unsupported_compression(self):
  from tools.l3_model_bridge import upstream_headers
  h=upstream_headers({'Accept-Encoding':'gzip, br, zstd','Authorization':'client','x-api-key':'client'},'private-test')
  self.assertEqual(h['accept-encoding'],'identity')
  self.assertEqual(h['authorization'],'Bearer private-test')
  self.assertNotIn('x-api-key',h)
 def test_board_pause_and_scored_preservation(self):
  rows=[{'variant':'m--medium','model':'m','effort':'medium','status':'queued','enabled':False},
        {'variant':'m--max','model':'m','effort':'max','status':'queued','enabled':True}]
  d={'models':[],'tasks':[{'level':3,'key':'x','model_results':[{'model_id':'m--medium','status':'pending'}]},
                         {'level':3,'key':'y','model_results':[{'model_id':'m--medium','status':'scored','report':{'score':.8}}]}]}
  schedule_variants(d,rows)
  self.assertEqual(d['tasks'][0]['model_results'][0]['status'],'paused')
  self.assertEqual(d['tasks'][1]['model_results'][0]['status'],'scored')
  self.assertTrue(all(next(r for r in t['model_results'] if r['model_id']=='m--max')['status']=='pending' for t in d['tasks']))
if __name__=='__main__':unittest.main()
