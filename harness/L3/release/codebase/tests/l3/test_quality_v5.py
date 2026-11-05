import unittest
from harness.L3.Suite.quality_v5 import CHECKS, validate_verdict, aggregate

class AnchoredQualityTests(unittest.TestCase):
 def answer(self):
  return {'checks':{k:{'coverage':.8,'deviation':.3,'quality':.55,'quality_band':'prototype','status':'measured',
   'required_features':['fixed requirement'],'largest_deviation':'rough construction','achieved':'realized','discrepancies':'simplified',
   'evidence':['candidate']} for k in CHECKS}}
 def test_quality_is_not_squared_again(self):
  axes=validate_verdict(self.answer(),{'candidate'})
  self.assertAlmostEqual(axes['visual_quality'],.55)
 def test_contradictory_high_score_is_rejected(self):
  a=self.answer();a['checks']['detail']['quality']=.9
  with self.assertRaises(ValueError):validate_verdict(a,{'candidate'})
 def test_absent_content_cannot_earn_credit(self):
  a=self.answer();a['checks']['detail']['coverage']=0
  with self.assertRaises(ValueError):validate_verdict(a,{'candidate'})
 def test_unknown_evidence_keeps_total_missing(self):
  a=self.answer();a['checks']['detail'].update(status='evidence_invalid',coverage=None,deviation=None,quality=None)
  q=validate_verdict(a,{'candidate'})
  base={'axes':{'layout':{'score':1},'interaction':{'score':1}}}
  self.assertIsNone(aggregate(base,q)['score_100'])
 def test_cannot_compensate_visually_absent_with_mechanics(self):
  base={'axes':{'layout':{'score':1},'interaction':{'score':1}}}
  self.assertAlmostEqual(aggregate(base,{'visual_quality':0,'task_fidelity':0})['score_100'],20)
 def test_continuous_ranking_is_monotonic(self):
  a=self.answer();b=self.answer();b['checks']['detail']['quality']=.6
  self.assertGreater(validate_verdict(b,{'candidate'})['visual_quality'],validate_verdict(a,{'candidate'})['visual_quality'])
if __name__=='__main__':unittest.main()
