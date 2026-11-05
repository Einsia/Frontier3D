import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODELS = [
    'gpt-6-astra', 'gpt-6.1-sol', 'gpt-6-luna', 'claude-opus-5-5',
    'glm-5.3-flash', 'kimi-k3', 'deepseek-v4.1-flash', 'qwen3.8-max',
    'MiniMax-M3.1-Flash', 'doubao-seed-evolving', 'kimi-k3.1-pro',
]

class EvaluatedModels(unittest.TestCase):
    def load_model(self, model):
        return subprocess.run(
            [sys.executable, '-c',
             'import json; from harness.L3.Suite.policy import MODEL, MODEL_SLUG, POLICY; '
             'print(json.dumps([MODEL, MODEL_SLUG, POLICY]))'],
            cwd=ROOT, env={**os.environ, 'L3_EVAL_MODEL': model},
            capture_output=True, text=True, timeout=30)

    def test_all_authorized_models_import_with_identical_measurement_policy(self):
        baseline = json.loads(self.load_model('gpt-6-astra').stdout)[2]
        for model in MODELS:
            with self.subTest(model=model):
                result = self.load_model(model)
                self.assertEqual(result.returncode, 0, result.stderr)
                identity, slug, policy = json.loads(result.stdout)
                self.assertEqual(identity, model)
                self.assertEqual(policy, baseline)

    def test_sol_generations_keep_distinct_identity_and_paths(self):
        old = json.loads(self.load_model('gpt-6-sol').stdout)
        new = json.loads(self.load_model('gpt-6.1-sol').stdout)
        self.assertNotEqual(old[:2], new[:2])
        self.assertNotEqual(old[1], new[1])

    def test_unknown_model_is_rejected(self):
        result = self.load_model('not-an-authorized-model')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsupported evaluated model', result.stderr)

if __name__ == '__main__':
    unittest.main()
