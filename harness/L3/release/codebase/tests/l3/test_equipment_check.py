import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from tools.l3_equipment_check import inspect_equipment

class EquipmentImageTests(unittest.TestCase):
    def check(self, black_sky=False, black_interior=False):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);out=np.full((360,640,3),[90,130,180],dtype=np.uint8)
            inside=np.tile(np.linspace(40,140,640,dtype=np.uint8),(360,1));inside=np.stack([inside]*3,axis=2)
            if black_sky:out[:30]=0
            if black_interior:inside[:]=0
            Image.fromarray(out).save(r/'out.png');Image.fromarray(inside).save(r/'in.png')
            return inspect_equipment(r/'out.png',r/'in.png')
    def test_missing_sky_blocks_equipment_readiness(self):
        self.assertFalse(self.check(black_sky=True)['passed'])
    def test_black_interior_blocks_equipment_readiness(self):
        self.assertFalse(self.check(black_interior=True)['passed'])
    def test_visible_sky_and_readable_interior(self):
        self.assertTrue(self.check()['passed'])
