import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from harness.L3.MinecraftVillage.protocol import digest, tree_digest, VIEWS
from harness.L3.MinecraftVillage.review_evidence import review_context


class ReviewEvidenceTests(unittest.TestCase):
    def setup_fixture(self, root):
        trial=root/'trial';run=root/'verification'
        project=trial/'workspace/project';project.mkdir(parents=True)
        (project/'scene.cpp').write_text('frozen source')
        verified=run/'workspace/project';verified.mkdir(parents=True)
        (verified/'scene.cpp').write_text('trusted observer build')
        (trial/'submission-manifest.json').write_text('{}')
        (trial/'trial.json').write_text(json.dumps({'status':'generated_awaiting_independent_verification','model':'gpt-5.6-luna','submission_manifest_sha256':digest(trial/'submission-manifest.json')}))
        (trial/'workspace/input').mkdir()
        (trial/'workspace/PROMPT.md').write_text('public brief')
        Image.new('RGB',(8,8)).save(trial/'workspace/input/reference.jpg')
        (trial/'preflight-complete.json').write_text(json.dumps({'input_and_material_hashes':{p:digest(trial/'workspace'/p) for p in ['PROMPT.md','input/reference.jpg']}}))
        frames=run/'workspace/episodes/views';frames.mkdir(parents=True)
        for name in list(VIEWS)+[f'building_{i:02}_interior{yaw}' for i in range(11) for yaw in (0,90,180,270)]:Image.new('RGB',(8,8)).save(frames/(name+'.png'))
        record={'kind':'submission_verification','status':'measured','source_sha256':tree_digest(project),'verification_source_sha256':tree_digest(verified),'episodes':{'views':{'completed':True}}}
        (run/'run.json').write_text(json.dumps(record))
        return run,trial,record

    def test_review_is_bound_to_frozen_submission_and_real_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            run,trial,_=self.setup_fixture(Path(tmp))
            evidence,metadata=review_context(run,trial)
            self.assertEqual(evidence,run/'workspace')
            self.assertEqual(metadata['tested_model'],'gpt-5.6-luna')
            self.assertEqual(len(metadata['frozen_image_hashes']),50)
            (trial/'workspace/project/scene.cpp').write_text('changed source')
            with self.assertRaisesRegex(ValueError,'different submission'):review_context(run,trial)

    def test_failed_objective_measurement_does_not_invalidate_completed_visual_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            run,trial,record=self.setup_fixture(Path(tmp))
            record.update(status='failed',error='geometry failed')
            (run/'run.json').write_text(json.dumps(record))
            _,metadata=review_context(run,trial)
            self.assertEqual(metadata['verification_error'],'geometry failed')
            (run/'workspace/episodes/views/street.png').write_bytes(b'invalid image')
            with self.assertRaises(Exception):review_context(run,trial)

    def test_incomplete_capture_is_not_scored(self):
        with tempfile.TemporaryDirectory() as tmp:
            run,trial,record=self.setup_fixture(Path(tmp))
            record['episodes']['views']['completed']=False
            (run/'run.json').write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError,'incomplete'):review_context(run,trial)
