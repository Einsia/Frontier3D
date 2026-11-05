import json
import unittest
from collections import Counter
from pathlib import Path
from harness.L3.scoring import metric_template, rubric_results, RUBRIC_AXES
from harness.L3.MinecraftVillage.evaluate import aggregate


class ScoringContractTests(unittest.TestCase):
    def test_text_accuracy_is_inapplicable_not_zero(self):
        report = metric_template('text')
        for axis in report['deterministic']['reference_accuracy'].values():
            self.assertEqual(axis, {'status': 'not_applicable', 'value': None})

    def test_image_accuracy_requires_annotations(self):
        report = metric_template('image')
        self.assertIsNone(report['score'])
        self.assertIsNone(report['weights'])
        for axis in report['deterministic']['reference_accuracy'].values():
            self.assertEqual(axis['status'], 'pending_annotations')

    def test_high_visual_scores_cannot_certify_physics_or_inventory(self):
        visual = {'verdicts': {key: {'median': 4, 'needs_human_review': False}
                              for key in [*RUBRIC_AXES, 'layout', 'components', 'e2e']}}
        report = aggregate({'journey': {'passed': True}}, visual, {'automatic_pass': True})
        self.assertTrue(all(v['value'] == 4 for v in report['rubrics'].values()))
        self.assertIsNone(report['deterministic']['layout']['value'])
        self.assertIsNone(report['deterministic']['interaction']['value'])
        self.assertIsNone(report['core_workflow_completed'])
        self.assertIsNone(report['score'])

    def test_visual_review_retains_missingness(self):
        out = rubric_results({'verdicts': {'beauty': {'median': 4, 'needs_human_review': True}}})
        self.assertIsNone(out['beauty']['value'])
        self.assertEqual(out['beauty']['status'], 'needs_review')
        self.assertEqual(out['style_consistency']['status'], 'pending_judgment')

    def test_invalid_rubric_score_rejected(self):
        for value in [True, 5, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                rubric_results({'verdicts': {'beauty': {'median': value, 'needs_human_review': False}}})

    def test_suite_split_and_readiness_are_explicit(self):
        root = Path(__file__).resolve().parents[2]
        catalog = json.loads((root/'benchmarks/l3/suite.json').read_text())
        tasks = catalog['tasks']
        self.assertEqual(len(tasks), 15)
        self.assertEqual(len({t['id'] for t in tasks}), 15)
        counts = Counter((t['domain'], t['input_mode']) for t in tasks)
        self.assertEqual(counts, {('game', 'image'): 4, ('game', 'text'): 2,
                                 ('embodied', 'image'): 4, ('embodied', 'text'): 2,
                                 ('real_world', 'image'): 2, ('real_world', 'text'): 1})
        self.assertTrue(all(t['status'] in {'proposed', 'pilot_unvalidated'} for t in tasks))
        self.assertTrue(all(len(t['zones']) >= 4 and len(t['mechanism_families']) >= 4 for t in tasks))
        self.assertIsNone(catalog['weights'])
        self.assertEqual(sum(t['task_path'] is not None for t in tasks), 1)


if __name__ == '__main__':
    unittest.main()
