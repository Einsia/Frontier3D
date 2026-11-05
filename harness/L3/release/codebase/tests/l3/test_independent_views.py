import hashlib,json
import pytest
from harness.L3.Suite.independent_views import selected_views

def fixture(tmp_path,meta):
    views=tmp_path/'workspace/episodes/views';views.mkdir(parents=True)
    hashes={}
    for name in meta:
        p=views/(name+'.png');p.write_bytes(name.encode())
        hashes[str(p.relative_to(tmp_path))]=hashlib.sha256(p.read_bytes()).hexdigest()
    (views/'completed.json').write_text(json.dumps({'completed':True}))
    (tmp_path/'views-metadata.json').write_text(json.dumps(meta))
    (tmp_path/'run.json').write_text(json.dumps({'status':'collected','evidence_sha256':hashes}))
    return tmp_path

def test_normal_views_keep_same_order_and_selection(tmp_path):
    root=fixture(tmp_path,{'a':{'kind':'view'},'r':{'kind':'reference','yaw_delta':0},'b':{'kind':'view'}})
    assert [n for n,_ in selected_views(root)]==['a','b']

def test_reference_camera_fallback_uses_all_base_captures(tmp_path):
    root=fixture(tmp_path,{'r0':{'kind':'reference','yaw_delta':0},'r0_left':{'kind':'reference','yaw_delta':-12},'r1':{'kind':'reference','yaw_delta':0}})
    assert [n for n,_ in selected_views(root)]==['r0','r1']

@pytest.mark.parametrize('failure',['hash','missing','incomplete','uncollected'])
def test_invalid_evidence_rejected(tmp_path,failure):
    root=fixture(tmp_path,{'r':{'kind':'reference','yaw_delta':0}})
    if failure=='hash':(root/'workspace/episodes/views/r.png').write_bytes(b'changed')
    if failure=='missing':(root/'workspace/episodes/views/r.png').unlink()
    if failure=='incomplete':(root/'workspace/episodes/views/completed.json').write_text('{"completed":false}')
    if failure=='uncollected':(root/'run.json').write_text('{"status":"failed"}')
    with pytest.raises((ValueError,RuntimeError)):selected_views(root)

def test_no_captures_not_replaced_with_reference_assets(tmp_path):
    root=fixture(tmp_path,{})
    (root/'reference.png').write_bytes(b'not candidate')
    with pytest.raises(RuntimeError):selected_views(root)
