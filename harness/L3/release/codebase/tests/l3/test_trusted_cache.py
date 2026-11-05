import json
import tempfile
import unittest
from pathlib import Path
from tools.verify_l3_submission import seed_trusted_cache
from harness.L3.MinecraftVillage.protocol import digest

class TrustedCacheTests(unittest.TestCase):
    def test_preflight_cache_is_verified_and_copied_without_candidate_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'source';source.mkdir();(source/'shader').write_bytes(b'public shader')
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'provenance':'organizer_preflight','captured_before_candidate_generation':True,'files':{'shader':digest(source/'shader')}}))
            result=seed_trusted_cache(source,manifest,root/'dest')
            self.assertEqual(result['file_count'],1)
            self.assertEqual((root/'dest/shader').read_bytes(),b'public shader')
            (source/'shader').write_bytes(b'changed')
            with self.assertRaises(ValueError):seed_trusted_cache(source,manifest,root/'other')

    def test_candidate_cache_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'provenance':'candidate','captured_before_candidate_generation':False,'files':{}}))
            with self.assertRaises(ValueError):seed_trusted_cache(root,manifest,root/'dest')
