import json
from pathlib import Path
import tempfile
import unittest
from tools.continue_l3_suite import choose_next
from tools.resume_l3_preflight import validate_parked


class QueueTests(unittest.TestCase):
    def test_ready_model_goes_before_unavailable_model_and_all_jobs_are_kept(self):
        pending = ['luna-parked', 'luna-new', 'astra-1', 'astra-2']
        byid = {rid: {'model': 'gpt-6-astra' if rid.startswith('astra') else 'gpt-6-luna'} for rid in pending}
        parked = {'luna-parked': 4}
        self.assertEqual(choose_next(pending, byid, parked, 4), 'astra-1')
        self.assertEqual(pending, ['luna-parked', 'luna-new', 'astra-1', 'astra-2'])
        pending.remove('astra-1')
        self.assertEqual(choose_next(pending, byid, parked, 4), 'astra-2')
        pending.remove('astra-2')
        self.assertEqual(choose_next(pending, byid, parked, 4), 'luna-parked')
        self.assertEqual(choose_next(pending, byid, parked, 9), 'luna-new')
        self.assertIsNone(choose_next(['luna-parked'], byid, parked, 9))
        parked['astra-2'] = 4
        self.assertEqual(choose_next(['luna-parked', 'astra-2'], byid, parked, 4), 'astra-2')

    def test_parked_resume_rejects_authored_or_changed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for status, started in [('generating', None), ('retrying_model_connection', 1)]:
                (root / 'trial.json').write_text(json.dumps({'status': status, 'started_unix': started}))
                with self.assertRaises(RuntimeError):
                    validate_parked(root)
            (root / 'trial.json').write_text(json.dumps({'status': 'queued_model_connection'}))
            (root / 'workspace').mkdir()
            (root / 'workspace/PROMPT.md').write_text('changed')
            (root / 'preflight-complete.json').write_text(json.dumps({'input_and_material_hashes': {'PROMPT.md': 'incorrect'}}))
            with self.assertRaisesRegex(RuntimeError, 'input changed'):
                validate_parked(root)


if __name__ == '__main__':
    unittest.main()
