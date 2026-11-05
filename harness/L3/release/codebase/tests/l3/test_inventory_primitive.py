import unittest
from harness.L3.MinecraftVillage.inventory import counts


class InventoryPrimitiveTests(unittest.TestCase):
    def test_candidate_state_never_substitutes_runtime_inventory(self):
        self.assertIsNone(counts({'entities':[{'candidate_state':{'seeds':'1'}}]}))

    def test_missing_duplicate_negative_and_unknown_inventory_are_rejected(self):
        for entries in [[],[{'counts':{}},{'counts':{}}],[{'counts':{'seeds':-1}}],
                        [{'counts':{'seeds':True}}],[{'counts':{'secret_item':1}}]]:
            with self.assertRaises(ValueError):counts({'trusted_inventory':entries})

    def test_absent_zero_counters_have_consistent_semantics(self):
        self.assertEqual(counts({'trusted_inventory':[{'counts':{'seeds':1}}]}),[1,0,0,0])


if __name__=='__main__':unittest.main()
