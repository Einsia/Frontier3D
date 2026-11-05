import copy
import unittest
from harness.L3.MinecraftVillage.rubric import CHECKS
from harness.L3.MinecraftVillage.rubric_batch import checklist_schema,validate_checklist

class BatchTests(unittest.TestCase):
    def item(self):
        return {'score':3,'not_judgeable':False,'confidence':.9,'evidence':['image.png'],
                'critical_failures':[],'achieved':'Visible shape','discrepancies':'Minor seam','discrepancy_severity':'minor'}
    def test_schema_requires_all_items(self):
        s=checklist_schema({'type':'object'})
        self.assertEqual(set(s['required']),set(CHECKS));self.assertFalse(s['additionalProperties'])
    def test_invalid_item_does_not_erase_other_valid_items(self):
        v={k:self.item() for k in CHECKS};bad=next(iter(v));v[bad]['score']=4
        got,errors=validate_checklist(v,['image.png'])
        self.assertIsNone(got[bad]);self.assertEqual(len(errors),1)
        self.assertEqual(sum(x is not None for x in got.values()),10)
    def test_missing_evidence_remains_null(self):
        v={k:self.item() for k in CHECKS};bad=next(iter(v));v[bad].update(score=None,not_judgeable=True)
        got,errors=validate_checklist(v,['image.png'])
        self.assertFalse(errors);self.assertIsNone(got[bad]['score'])
    def test_unknown_image_citation_is_rejected(self):
        v={k:self.item() for k in CHECKS};bad=next(iter(v));v[bad]['evidence']=['invented.png']
        got,errors=validate_checklist(v,['image.png']);self.assertIn(bad,errors)
