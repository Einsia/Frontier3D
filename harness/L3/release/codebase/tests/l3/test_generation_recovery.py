import json
from pathlib import Path
from tools.recover_l3_generation import relocated_command
from tools.l3_delivery import delivery_feedback,sha

def test_relocation_preserves_workspace_and_asset_mounts():
    e={'engine_copy':'/old','gateway_directory':'/gw','docker_command':['docker','run','--name','old','--gpus','device=0','--mount','type=bind,src=/old,dst=/engine','--mount','type=bind,src=/gw,dst=/model-gateway,readonly','--mount','type=bind,src=/project,dst=/workspace']}
    cmd=relocated_command(e,Path('/new'),3,Path('/newgw'),'new')
    assert 'type=bind,src=/new,dst=/engine' in cmd
    assert 'type=bind,src=/newgw,dst=/model-gateway,readonly' in cmd
    assert 'type=bind,src=/project,dst=/workspace' in cmd
    assert cmd[cmd.index('--gpus')+1]=='device=3'
    assert e['docker_command'][3]=='old'

def test_equipment_only_submission_needs_scene_implementation(tmp_path):
    p=tmp_path/'project';(p/'Source').mkdir(parents=True)
    (p/'Source/A.cpp').write_text('fixture')
    (p/'X.uproject').write_text('{}')
    for n in ['README.md','bindings.json','assets_used.json']:(p/n).write_text('{}')
    (tmp_path/'agent-final.txt').write_text('done')
    (tmp_path/'checks/final').mkdir(parents=True)
    (tmp_path/'checks/final/preview.png').write_bytes(b'png')
    initial={str(x.relative_to(p)):sha(x) for x in p.rglob('*') if x.is_file()}
    timing={'generation_status':'completed','terminal_event':'turn.completed','return_code':0}
    assert 'replace the generic equipment fixture' in delivery_feedback(tmp_path,timing,False,initial)
    (p/'Source/A.cpp').write_text('authored scene')
    assert delivery_feedback(tmp_path,timing,False,initial) is None
