import copy
import unittest
from harness.L3.MinecraftVillage.protocol import DOORS
from harness.L3.MinecraftVillage.calibration import ground_plan,apply_ground_observations

class GroundCalibrationTests(unittest.TestCase):
    def fixture(self):
        b={'entities':{t:{'crossing_from_cm':[0,-110,89],'crossing_to_cm':[0,110,89]} for t in DOORS}}
        observations={s['name']:{'accepted':True,'blocked':True,'hit':'floor','point_cm':[0,0,4],
                               'normal':[0,0,1]} for s in ground_plan(b)['steps']}
        return b,observations

    def test_only_height_changes_and_original_submission_remains_frozen(self):
        b,obs=self.fixture();original=copy.deepcopy(b)
        result,evidence=apply_ground_observations(b,obs)
        self.assertEqual(b,original)
        self.assertEqual(result['entities'][DOORS[0]]['crossing_from_cm'],[0,-110,92])
        self.assertTrue(evidence[DOORS[0]]['closed_probe_must_still_hit_target'])

    def test_missing_steep_roof_or_door_hit_is_not_a_valid_floor(self):
        for change in [{'blocked':False},{'normal':[1,0,0]},{'point_cm':[0,0,250]},{'hit':DOORS[0]}]:
            with self.subTest(change=change):
                b,obs=self.fixture();obs[DOORS[0].replace('.','_')+'_front'].update(change)
                result,evidence=apply_ground_observations(b,obs)
                self.assertEqual(evidence[DOORS[0]]['status'],'unresolved_ground')
                self.assertEqual(result["entities"][DOORS[0]],b["entities"][DOORS[0]])


def test_missing_crossing_does_not_block_other_calibrations():
    b={'entities':{DOORS[1]:{'crossing_from_cm':[0,0,85],'crossing_to_cm':[200,0,85]}}}
    plan=ground_plan(b)
    assert len(plan['steps'])==2
    result,evidence=apply_ground_observations(b,{})
    assert evidence[DOORS[0]]['status']=='submission_contract_failure'
    assert evidence[DOORS[1]]['status']=='unresolved_ground'
    assert result==b


def test_no_crossing_yields_no_fake_rays_or_calibration():
    b={'entities':{}}
    assert ground_plan(b)['steps'][0]['op']=='wait'
    result,evidence=apply_ground_observations(b,{})
    assert all(e['status']=='submission_contract_failure' for e in evidence.values())
