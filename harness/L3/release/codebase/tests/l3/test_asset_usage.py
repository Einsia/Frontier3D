import tempfile
import unittest
from pathlib import Path
from harness.L3.MinecraftVillage.asset_usage import audit
from harness.L3.MinecraftVillage.protocol import digest

class AssetUsageTests(unittest.TestCase):
    def test_imported_pack_is_not_usage_and_dynamic_material_base_is_resolved(self):
        texture='/Game/L3Materials/T_wood.T_wood';material='/Game/L3Materials/M_wood.M_wood'
        imported={'assets':[{'id':'wood','texture':texture,'material':material},
                            {'id':'stone','texture':'/Game/T_stone.T_stone','material':'/Game/M_stone.M_stone'}]}
        geometry={'instances':[{'visible':True,'materials':['dynamic','']}],
                  'material_catalog':{'dynamic':{'base_material':material,'texture_assets':[texture]}}}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'Content/L3Materials/T_wood.uasset';p.parent.mkdir(parents=True);p.write_bytes(b'original')
            hashes={'project/Content/L3Materials/T_wood.uasset':digest(p)}
            result=audit(geometry,imported,Path(tmp),hashes)
            self.assertEqual(result['used_materials'],1)
            self.assertTrue(result['materials'][0]['texture_bytes_match_preloaded_assets'][texture])
            self.assertEqual(result['unresolved_material_references'],[])
            self.assertEqual(result['unassigned_material_slots'],1)
            p.write_bytes(b'changed')
            self.assertFalse(audit(geometry,imported,Path(tmp),hashes)['materials'][0]['texture_bytes_match_preloaded_assets'][texture])

    def test_missing_engine_observation_is_not_zero_usage(self):
        result=audit({'instances':[]},{'assets':[]})
        self.assertEqual(result['status'],'missing_runtime_material_evidence')
        self.assertIsNone(result['value'])
