import copy, math, unittest
from harness.L3.Suite.quality_v4 import CHECKS, WEIGHTS, validate_verdict, aggregate
from tools.publish_l3_matrix_scores import isolate_protocol

class QualityTests(unittest.TestCase):
 def verdict(self,c=.8,e=.2):
  return {'checks':{k:{'coverage':c,'deviation':e,'status':'measured','required_features':['frozen feature'],
   'largest_deviation':'shape differs','achieved':'visible structure','discrepancies':'missing detail','evidence':['candidate']} for k in CHECKS}}
 def base(self,layout=1.,interaction=1.):
  return {'axes':{'layout':{'score':layout},'interaction':{'score':interaction}}}
 def test_continuous_fidelity_formula(self):
  x=validate_verdict(self.verdict(),{'candidate'})
  self.assertAlmostEqual(x['visual_quality'],.8*.8**2)
 def test_missing_requirement_remains_penalty(self):
  a=validate_verdict(self.verdict(.9,.1),{'candidate'})
  b=validate_verdict(self.verdict(.5,.1),{'candidate'})
  self.assertLess(b['task_fidelity'],a['task_fidelity'])
 def test_shape_deviation_cannot_be_offset_by_presence(self):
  a=validate_verdict(self.verdict(1,.1),{'candidate'})
  b=validate_verdict(self.verdict(1,.5),{'candidate'})
  self.assertLess(b['visual_quality'],a['visual_quality'])
 def test_no_technical_success_floor(self):
  r=aggregate(self.base(),{'visual_quality':0,'task_fidelity':0})
  self.assertAlmostEqual(r['score_100'],20)
 def test_no_missingness_renormalization(self):
  self.assertIsNone(aggregate(self.base(interaction=None),{'visual_quality':1,'task_fidelity':1})['score_100'])
 def test_bad_capture_not_automatically_perfect(self):
  v=self.verdict();v['checks']['lighting'].update(status='evidence_invalid',coverage=None,deviation=None)
  self.assertIsNone(validate_verdict(v,{'candidate'})['visual_quality'])
 def test_reject_nonfinite_and_boolean(self):
  for x in [float('nan'),float('inf'),-1,1.1,True]:
   v=self.verdict();v['checks']['lighting']['coverage']=x
   with self.assertRaises(ValueError):validate_verdict(v,{'candidate'})
 def test_reject_reference_only_citation(self):
  with self.assertRaises(ValueError):validate_verdict(self.verdict(),{'other'})
 def test_fixed_population(self):
  v=self.verdict();v['checks'].pop('materials')
  with self.assertRaises(ValueError):validate_verdict(v,{'candidate'})
 def test_weights_and_bounds(self):
  self.assertAlmostEqual(sum(WEIGHTS.values()),1)
  self.assertEqual(aggregate(self.base(),{'visual_quality':1,'task_fidelity':1})['score_100'],100)
 def test_protocol_isolation_preserves_history_and_other_levels(self):
  old={'model_id':'v','protocol':'old','matrix_summary_sha256':'hash','score_100':80}
  other={'key':'l2','level':2,'evaluation_results':[copy.deepcopy(old)]}
  task={'key':'l3','level':3,'evaluation_results':[copy.deepcopy(old)],'model_results':[{'model_id':'v','report':{'score':.8}}],
   'generation_runs':[{'model':'v','score':80,'evaluation_result':{'score_100':80}}]}
  data={'tasks':[task,other]};saved=copy.deepcopy(other)
  rows=[{'task_key':'l3','variant':'v','enabled':True}]
  self.assertEqual(len(isolate_protocol(data,rows,'new')),1)
  self.assertEqual(task['evaluation_history'],[old]);self.assertEqual(other,saved)
  self.assertEqual(task['model_results'][0]['report'],{});self.assertNotIn('score',task['generation_runs'][0])
  self.assertEqual(isolate_protocol(data,rows,'new'),[])
 def test_disabled_historical_rows_stay_intact(self):
  task={'key':'l3','level':3,'evaluation_results':[{'model_id':'v','protocol':'old'}]}
  before=copy.deepcopy(task)
  isolate_protocol({'tasks':[task]},[{'task_key':'l3','variant':'v','enabled':False}],'new')
  self.assertEqual(task,before)

if __name__=='__main__':unittest.main()
