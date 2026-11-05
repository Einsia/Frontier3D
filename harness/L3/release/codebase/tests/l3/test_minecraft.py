import copy, json, tempfile, unittest, zipfile, hashlib
from pathlib import Path
from harness.L3.MinecraftVillage.protocol import *
from harness.L3.MinecraftVillage.evaluate import changed,movement,meshes,aggregate,entity,summarize,local_diagnostics
from harness.L3.MinecraftVillage.install_engine import install

class EvidenceTests(unittest.TestCase):
    def component(self):
        return {'id':'door','components':[{'name':'leaf','mesh':'/Engine/Cube','instances':1,'visible':True,'collision':True,'position_cm':[0,0,0],'rotation_deg':[0,0,0],'bounds_extent_cm':[5,50,100]}]}
    def test_candidate_success_json_cannot_move_door(self):
        a=self.component();b=copy.deepcopy(a);b['candidate_state']={'open':'true','success':'true'}
        self.assertFalse(changed(a,b));self.assertEqual(movement(a,b),(0,0))
    def test_real_hinge_rotation_observed(self):
        a=self.component();b=copy.deepcopy(a);b['components'][0]['rotation_deg']=[0,0,90]
        self.assertEqual(movement(a,b)[0],90);self.assertTrue(changed(a,b))
    def test_rotation_wrap(self):
        a=self.component();b=copy.deepcopy(a);a['components'][0]['rotation_deg']=[0,0,359];b['components'][0]['rotation_deg']=[0,0,1]
        self.assertEqual(movement(a,b)[0],2)
    def test_fake_tag_without_geometry(self):self.assertFalse(meshes({'id':'building.house01','components':[]}))
    def test_duplicate_id_rejected(self):
        with self.assertRaises(ValueError):entity({'entities':[{'id':'x'},{'id':'x'}]},'x')
    def test_hiding_mesh_not_same_as_opening(self):
        a=self.component();a['components'][0]['visible']=False;self.assertFalse(meshes(a))
    def test_instance_zero_is_not_geometry(self):
        a=self.component();a['components'][0]['instances']=0;self.assertFalse(meshes(a))
    def test_e2e_teleport_rejected(self):
        with self.assertRaises(ValueError):validate_plan({'kind':'e2e','steps':[dict(op='fixture',name='x',purpose='local_test_setup',position_cm=[0,0,100])]})
    def test_path_traversal_name_rejected(self):
        with self.assertRaises(ValueError):validate_plan({'kind':'views','steps':[dict(op='capture',name='../escape')]})
    def test_reserved_evidence_name_rejected(self):
        with self.assertRaises(ValueError):validate_plan({'kind':'views','steps':[dict(op='snapshot',name='completed')]})
    def test_nonfinite_position_rejected(self):
        with self.assertRaises(ValueError):vector([0,float('nan'),0])
    def test_source_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):tree_digest(p)
    def test_missing_judge_does_not_renormalize(self):
        self.assertIsNone(aggregate({}, {'verdicts':{}},{})['score'])
    def test_missing_engine_is_not_zero_quality(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);write_json(p/'run.json',{'status':'needs_engine'})
            result=summarize(p);self.assertEqual(result['status'],'needs_engine');self.assertIsNone(result['score'])
    def test_local_plan_has_far_negative_and_repeat(self):
        b={'approach_cm':[0,0,90],'look_cm':[100,0,100],'crossing_from_cm':[0,0,90],'crossing_to_cm':[200,0,90]}
        p=local_plan(DOORS[0],b);self.assertEqual(sum(s['op'] in {'interact','invoke'} for s in p['steps']),4)
        self.assertIn('cross_walk',[s['name'] for s in p['steps']])
    def test_high_visual_score_cannot_hide_core_door_failure(self):
        verdicts={k:{'median':4,'needs_human_review':False} for k in ['aesthetics','layout','components','e2e']+REQUIRED+BUILDINGS}
        report={'episodes':{t:{'automatic_fraction':1.,'checks':{'passed':True}} for t in REQUIRED},'journey':{'passed':True},'component_presence':1.}
        report['episodes'][DOORS[0]]={'automatic_fraction':.9,'checks':{'opened_passage':False}}
        result=aggregate(report,{'verdicts':verdicts},{'automatic_pass':True})
        self.assertIsNone(result['score']);self.assertFalse(result['core_workflow_completed'])
        self.assertIsNone(result['weights'])
    def test_fake_success_fails_complete_door_diagnostic(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);target=DOORS[0];e=self.component();e['id']=target;e['candidate_state']={'open':'true'}
            for name in ['before','after_1','after_2','after_3','far_before','far_after','crossed']:
                write_json(p/(name+'.json'),{'protocol':'ue5-observer-v1','entities':[e],'pawn_position_cm':[200,0,90]})
            write_json(p/'completed.json',{'completed':True})
            for i in [1,2,3]:write_json(p/f'action_{i}_event.json',{'accepted':True})
            write_json(p/'far_action_event.json',{'dispatched':True})
            for name in ['closed_probe','probe_2']:write_json(p/(name+'_event.json'),{'blocked':True,'hit':target})
            for name in ['probe_1','probe_3']:write_json(p/(name+'_event.json'),{'blocked':False,'hit':''})
            result=local_diagnostics(p,{'target':target},{'crossing_to_cm':[200,0,90]})
            self.assertFalse(result['checks']['leaf_rotates'])
            self.assertFalse(result['checks']['sampled_intermediate_motion'])
            self.assertLess(result['automatic_fraction'],1)
            write_json(p/'closed_probe_event.json',{'blocked':True,'hit':'path.17'})
            invalid=local_diagnostics(p,{'target':target},{'crossing_to_cm':[200,0,90]})
            self.assertEqual(invalid['check_counts']['unresolved'],3)
            self.assertIsNone(invalid['checks']['opened_passage'])
            self.assertEqual(invalid['diagnostics']['probe_validation']['closed_probe_hit'],'path.17')
    def test_uncalibrated_measurements_are_not_known_failures(self):
        report={'episodes':{'door':{'automatic_fraction':.5,'checks':{'geometry':True,'opened_passage':None}}}}
        self.assertIsNone(aggregate(report,{}, {'automatic_pass':False,'route_validated':False})['core_workflow_completed'])
        self.assertFalse(aggregate(report,{}, {'automatic_pass':False,'route_validated':True})['core_workflow_completed'])

    def test_negative_invocation_cannot_enter_e2e(self):
        with self.assertRaises(ValueError):validate_plan({'kind':'e2e','steps':[dict(op='invoke',name='x',target=DOORS[0],action='use')]})
    def test_archive_traversal_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);z=p/'a.zip'
            with zipfile.ZipFile(z,'w') as f:f.writestr('../outside','x')
            with self.assertRaises(ValueError):install(z,p/'engine',digest(z))
            self.assertFalse((p/'outside').exists())
    def test_checksum_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);z=p/'a.zip';z.write_bytes(b'not an engine')
            with self.assertRaises(ValueError):install(z,p/'engine','0'*64)

if __name__=='__main__':unittest.main()
