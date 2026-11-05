import json
from tools.l3_leaderboard_batch import pending_engine_reservations

def row(tmp_path,name,status,slot=3,enabled=True):
    p=tmp_path/name;p.mkdir()
    (p/'state.json').write_text(json.dumps({'status':status}))
    (p/'environment.json').write_text(json.dumps({'engine_copy':'/engines/slot-%02d'%slot}))
    return {'id':name,'output':str(p),'enabled':enabled,'status':'queued'}

def test_failed_candidate_keeps_its_original_engine(tmp_path):
    r=row(tmp_path,'pending','failed')
    assert pending_engine_reservations([r])=={3:{'pending'}}

def test_completed_and_paused_candidates_do_not_reserve(tmp_path):
    a=row(tmp_path,'done','generated')
    b=row(tmp_path,'paused','failed',enabled=False)
    assert pending_engine_reservations([a,b])=={}

def test_shared_historical_slot_keeps_all_pending_owners(tmp_path):
    a=row(tmp_path,'first','failed');b=row(tmp_path,'second','preparing')
    assert pending_engine_reservations([a,b])=={3:{'first','second'}}
