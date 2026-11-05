from pathlib import Path
import json
import shutil
import pytest
from tools.validate_l3_suite import validate_task

ROOT=Path(__file__).resolve().parents[2]
TASK=ROOT/'tasks/L3/MinecraftVillageOpenWorld'

def test_mc_package_preserves_reference_and_open_world_without_time_cap():
    result=validate_task(TASK)
    assert result['task_key']=='l3-g01' and result['references']==1
    prompt=(TASK/'PROMPT.md').read_text()
    assert 'entire open-world Minecraft environment' in prompt
    assert 'within 3600 seconds' not in prompt
    assert 'until the complete deliverable is ready' in prompt
    runtime=json.loads((TASK/'runtime.json').read_text())
    assert runtime['time_limit_seconds'] is None
    assert runtime['reasoning_effort']=='high'

def test_mc_package_rejects_modified_reference(tmp_path):
    copied=tmp_path/'task'
    shutil.copytree(TASK,copied)
    with (copied/'environment/input/reference.jpg').open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='Missing or changed file'):validate_task(copied)
