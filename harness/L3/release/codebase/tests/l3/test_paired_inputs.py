import json
import pytest
from tools.l3_paired_inputs import validate, sha

def test_paired_inputs_reject_changes_and_path_escape(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    public=tmp_path/'public';public.mkdir()
    (workspace/'PROMPT.md').write_text('same brief')
    value={'workspace':{'PROMPT.md':sha(workspace/'PROMPT.md')},'public':{}}
    (tmp_path/'paired-inputs.json').write_text(json.dumps(value))
    validate(tmp_path)
    (workspace/'PROMPT.md').write_text('different brief')
    with pytest.raises(ValueError,match='differs'):validate(tmp_path)
    value['workspace']={'../outside':'ignored'}
    (tmp_path/'paired-inputs.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='Invalid'):validate(tmp_path)
