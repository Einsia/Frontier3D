import json
import pytest
from tools.verify_l3_submission import diagnose_local


@pytest.mark.parametrize('entities', [[], [{'id':'chest'}, {'id':'chest'}]])
def test_missing_or_duplicate_target_is_a_submission_failure(tmp_path, entities):
    (tmp_path/'before.json').write_text(json.dumps({'protocol':'ue5-observer-v1','entities':entities}))
    result=diagnose_local(tmp_path,{'target':'chest'},{})
    assert result['status']=='submission_contract_failure'
    assert result['observed_target_count']==len(entities)
    assert result['automatic_fraction'] is None


def test_bad_observer_evidence_is_not_blame_on_candidate(tmp_path):
    (tmp_path/'before.json').write_text(json.dumps({'protocol':'invalid','entities':[]}))
    with pytest.raises(ValueError,match='observation protocol'):
        diagnose_local(tmp_path,{'target':'chest'},{})
