import json
import sys
import tempfile
import unittest
from pathlib import Path
from tools.l3_usage import UsageParser, append_record, summarize_requests, timed_generation

class UsageTests(unittest.TestCase):
    def test_chunked_sse_only_saves_counters(self):
        p=UsageParser()
        data=b'data: {"type":"response.output_text.delta","delta":"SECRET BODY"}\n\n'
        data+=b'data: {"type":"response.completed","response":{"id":"r1","usage":{"input_tokens":12,"output_tokens":7,"total_tokens":19,"input_tokens_details":{"cached_tokens":8},"output_tokens_details":{"reasoning_tokens":3}}}}\n\n'
        for i in range(0,len(data),7):p.feed(data[i:i+7])
        p.finish()
        self.assertEqual(p.usage['total_tokens'],19)
        self.assertEqual(p.usage['cached_input_tokens'],8)
        self.assertNotIn('SECRET',repr(vars(p)))
    def test_no_usage_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger'
            append_record(p,{'event':'request_started','attempt_id':'1','stage':'generation'})
            append_record(p,{'event':'request_finished','attempt_id':'1','http_status':429,'elapsed_seconds':5})
            s=summarize_requests(p)
            self.assertEqual(s['requests_without_usage'],1)
            self.assertIsNone(s['reported_tokens']['total_tokens'])
    def test_dedup_and_stages(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ledger'
            for i,stage in [('1','generation'),('2','generation'),('3','preflight_probe')]:
                append_record(p,{'event':'request_started','attempt_id':i,'stage':stage})
                append_record(p,{'event':'request_finished','attempt_id':i,'response_id':'same','usage':{'input_tokens':10,'output_tokens':2,'total_tokens':12}})
            self.assertEqual(summarize_requests(p)['reported_tokens']['total_tokens'],12)
            self.assertEqual(summarize_requests(p)['requests_started'],2)
    def test_timeout_preserves_events(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            r=timed_generation([sys.executable,'-c','import time;print(\'{"type":"turn.started"}\',flush=True);time.sleep(5)'],b'',p,.2)
            self.assertEqual(r['generation_status'],'timeout')
            self.assertIn('received_unix',(p/'agent-timeline.jsonl').read_text())
    def test_completed_captures_usage_event(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            r=timed_generation([sys.executable,'-c','print(\'{"type":"turn.completed","usage":{"input_tokens":2}}\')'],b'',p,2)
            self.assertEqual(r['generation_status'],'completed')
            self.assertIn('turn.completed',(p/'agent-events.jsonl').read_text())
    def test_explicit_unlimited_waits_for_completion(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            command=[sys.executable,'-c','import time;time.sleep(0.3);print(\'{"type":"turn.completed"}\')']
            result=timed_generation(command,b'',p,None)
            self.assertEqual(result['generation_status'],'completed')
            self.assertGreaterEqual(result['elapsed_seconds'],.3)
    def test_zero_exit_without_completed_turn_is_not_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            r=timed_generation([sys.executable,'-c','print("no terminal event")'],b'',p,2)
            self.assertEqual(r['generation_status'],'process_error')
            self.assertIsNone(r['terminal_event'])
if __name__=='__main__':unittest.main()
