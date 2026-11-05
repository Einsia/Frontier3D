import threading
import time
from concurrent.futures import ThreadPoolExecutor
from harness.L3.Suite import quality_v5

def test_primary_packet_serializes_independent_callers(tmp_path, monkeypatch):
    active=0
    maximum=0
    gate=threading.Lock()
    def fake(row,runtime,target,repeat):
        nonlocal active,maximum
        with gate:
            active+=1
            maximum=max(maximum,active)
        time.sleep(.05)
        with gate:
            active-=1
        return row
    monkeypatch.setattr(quality_v5,'_review_unlocked',fake)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(quality_v5.review,{'id':i},tmp_path,tmp_path) for i in range(2)]
        assert [f.result() for f in futures]==[{'id':0},{'id':1}]
    assert maximum==1
