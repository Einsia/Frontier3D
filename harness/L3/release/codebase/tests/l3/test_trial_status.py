import json
import tempfile
import unittest
from pathlib import Path
from tools.l3_trial_status import has_authoring_activity

class TrialStatusTests(unittest.TestCase):
    def inspect(self, events):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'events.jsonl'
            p.write_text('\n'.join(json.dumps(e) for e in events))
            return has_authoring_activity(p)

    def test_provider_failure_is_not_an_authoring_attempt(self):
        self.assertFalse(self.inspect([{'type':'thread.started'},{'type':'turn.started'},{'type':'error','message':'HTTP 502'}]))

    def test_partial_attempt_is_preserved_when_tools_have_started(self):
        self.assertTrue(self.inspect([{'type':'item.started','item':{'type':'command_execution','command':'build'}},{'type':'error'}]))

    def test_file_change_counts_without_a_shell_command(self):
        self.assertTrue(self.inspect([{'type':'item.completed','item':{'type':'file_change','changes':[]}}]))


def test_delivery_gate_requires_completion_and_real_preview(tmp_path):
    from tools.l3_trial_status import completion_evidence
    project = tmp_path / 'project'
    project.mkdir()
    for name in ['README.md','bindings.json','assets_used.json','Scene.uproject']:
        (project / name).write_text('{}')
    (tmp_path / 'agent-final.txt').write_text('Done')
    preview = tmp_path / 'checks/preflight-preview'
    preview.mkdir(parents=True)
    (preview / 'preview.png').write_bytes(b'fixture')
    done = {'generation_status':'completed','terminal_event':'turn.completed'}
    assert not completion_evidence(tmp_path, done)['delivery_complete']
    actual = tmp_path / 'checks/final'
    actual.mkdir()
    (actual / 'overview.png').write_bytes(b'scene')
    assert completion_evidence(tmp_path, done)['delivery_complete']
    assert not completion_evidence(tmp_path, {'generation_status':'process_error'})['delivery_complete']
