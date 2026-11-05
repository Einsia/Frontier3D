import unittest
from tools.report_l3_runtime import interval_union
class RuntimeTimingTests(unittest.TestCase):
    def test_overlapping_requests_are_not_double_counted(self):
        self.assertEqual(interval_union([(0,10),(5,15),(20,22)]),17)
    def test_invalid_clipped_intervals_are_ignored(self):
        self.assertEqual(interval_union([(10,5),(2,4)]),2)
