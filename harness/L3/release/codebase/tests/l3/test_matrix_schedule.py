import copy,unittest
from tools.publish_l3_matrix_scores import schedule_variants
class ScheduleTests(unittest.TestCase):
 def test_pending_has_no_score_and_preserves_existing_high(self):
  original={'model_id':'gpt-6-sol','status':'scored','report':{'score':.7}}
  data={'models':[{'id':'gpt-6-sol'}],'tasks':[{'key':'l3-g01','level':3,'model_results':[copy.deepcopy(original)]},{'key':'l2-a','level':2,'model_results':[]}]}
  row={'variant':'gpt-6-sol--medium','model':'gpt-6-sol','effort':'medium','status':'queued'}
  self.assertEqual(schedule_variants(data,[row]),['gpt-6-sol--medium'])
  self.assertEqual(data['tasks'][0]['model_results'][0],original)
  self.assertEqual(data['tasks'][0]['model_results'][1]['report'],{})
  self.assertEqual(data['tasks'][0]['model_results'][1]['status'],'pending')
  self.assertEqual(data['tasks'][1]['model_results'],[])
  self.assertEqual(schedule_variants(data,[row]),[])
 def test_reuse_does_not_duplicate_high(self):
  data={'models':[],'tasks':[{'level':3}]}
  self.assertEqual(schedule_variants(data,[{'status':'reused','variant':'gpt-6-sol--high'}]),[])
  self.assertEqual(data,{'models':[],'tasks':[{'level':3}]})
if __name__=='__main__':unittest.main()
