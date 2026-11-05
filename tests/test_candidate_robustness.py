import copy
import json

import pytest

from src.evaluator.candidate_robustness import resolve_checks, weighted_components
from test_candidate_content_partial_zero import retained_case


def test_undefined_checks_zero_without_losing_available_credit_or_hiding_infrastructure():
    rows = {'good': {'score': .8, 'measurement_status': 'passed'},
        'unknown': {'score': None, 'measurement_status': 'not_measurable'},
        'unsupported': {'score': 0., 'status': 'not_implemented'},
        'api': {'score': None, 'measurement_status': 'infrastructure_error'}}
    updated, changed = resolve_checks(rows)
    assert updated['good'] == rows['good']
    assert set(changed) == {'unknown', 'unsupported'}
    assert updated['unknown']['score'] == 0
    assert updated['api'] == rows['api']
    assert rows['unknown']['score'] is None
    assert weighted_components({'visual': .8, 'geometry': 0.}, {'visual': .7, 'geometry': .3}) == pytest.approx(.56)


def prepare(tmp_path, monkeypatch):
    from tools import recover_undefined_candidate as recovery
    path, evidence, job = retained_case(tmp_path, monkeypatch)
    policy = tmp_path/'policy.json'; policy.write_text('{"enabled":true}')
    monkeypatch.setattr(recovery, 'POLICY', policy)
    return recovery, path, evidence, job


def test_replay_preserves_original_positive_scores_and_is_independently_verified(tmp_path, monkeypatch):
    recovery, path, _, _ = prepare(tmp_path, monkeypatch)
    original_bytes = path.read_bytes()
    report = recovery.recover(path)
    assert report['S_core'] == pytest.approx(.77)
    assert report['score_components']['vlm'] == .9 and report['score_components']['physics'] == .8
    assert path.read_bytes() == original_bytes
    recovery.verify_recovery(report)
    bad = copy.deepcopy(report); bad['score_components']['vlm'] = 0
    with pytest.raises(ValueError, match='arithmetic or provenance'):
        recovery.verify_recovery(bad)


def test_recovery_uses_selected_race_winner_instead_of_original_generation(tmp_path, monkeypatch):
    recovery,path,_,job=prepare(tmp_path,monkeypatch)
    selected=job/'selected-generation.json'
    selected.write_bytes((job/'generate-result.json').read_bytes())
    original=json.loads((job/'generate-result.json').read_text())
    original['source_sha256']={'solution.py':'different-original-branch'}
    (job/'generate-result.json').write_text(json.dumps(original))
    report=recovery.recover(path)
    assert report['S_core']==pytest.approx(.77)
    assert str(selected.resolve()) in report['source_bindings']


def test_api_score_gap_and_changed_candidate_do_not_receive_content_zero(tmp_path, monkeypatch):
    recovery, path, _, job = prepare(tmp_path, monkeypatch)
    original = json.loads(path.read_text()); original['score_components']['vlm'] = None
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='API/judge'):
        recovery.recover(path)
    (job/'generation/source/solution.py').write_text('changed source')
    with pytest.raises(ValueError): recovery.recover(path)
    assert not path.with_name('robustness_report.json').exists()


def test_filesystem_and_infrastructure_faults_remain_recoverable(tmp_path, monkeypatch):
    recovery, path, _, _ = prepare(tmp_path, monkeypatch)
    original = json.loads(path.read_text())
    original['gates']['infrastructure'] = {'measurement_status': 'infrastructure_error'}
    path.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='Infrastructure gate'):
        recovery.recover(path)


def test_complexity_limit_zero_only_affects_physics(tmp_path, monkeypatch):
    recovery, path, _, _ = prepare(tmp_path, monkeypatch)
    original = json.loads(path.read_text())
    original['missing_components'] = ['physics']
    original['score_components'].update(data=.5, physics=None)
    original['measurements']['physics'].update(status='not_measurable', score=None,
        reason='Contact measurement exceeds one million complete triangles')
    path.write_text(json.dumps(original))
    report = recovery.recover(path)
    assert report['score_components']['physics'] == 0
    assert report['score_components']['data'] == .5
    assert report['S_core'] == pytest.approx(.69)
