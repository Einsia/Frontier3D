"""Content-free request accounting for streamed Responses; no credentials or text."""
import json
import os
import selectors
import subprocess
import time
from pathlib import Path

class UsageParser:
    def __init__(self):
        self.buffer = b''
        self.response_id = None
        self.usage = None
        self.terminal_event = None
        self.overflow = False
    def accept(self, value):
        if not isinstance(value, dict): return
        response = value.get('response', value)
        if not isinstance(response, dict): return
        if isinstance(response.get('id'), str): self.response_id = response['id']
        if value.get('type') in {'response.completed','response.failed','response.incomplete'}:
            self.terminal_event = value['type']
        usage = response.get('usage')
        if isinstance(usage, dict):
            # Explicit whitelist. Never persist text, tool arguments or error messages.
            def count(v): return v if type(v) is int and v >= 0 else None
            self.usage = {k: count(usage.get(k)) for k in ['input_tokens','output_tokens','total_tokens']}
            self.usage['cached_input_tokens'] = count((usage.get('input_tokens_details') or {}).get('cached_tokens'))
            self.usage['reasoning_output_tokens'] = count((usage.get('output_tokens_details') or {}).get('reasoning_tokens'))
    def feed(self, chunk):
        self.buffer += chunk
        while b'\n' in self.buffer:
            line,self.buffer=self.buffer.split(b'\n',1)
            if line.startswith(b'data:'):
                try:self.accept(json.loads(line[5:].strip()))
                except (ValueError,UnicodeDecodeError):pass
        if len(self.buffer)>8*1024*1024:
            self.buffer=b'';self.overflow=True
    def finish(self):
        # Non-streaming JSON responses and final lines without a newline.
        value=self.buffer.strip()
        if value.startswith(b'data:'):value=value[5:].strip()
        try:self.accept(json.loads(value))
        except (ValueError,UnicodeDecodeError):pass


def append_record(path, value):
    if not path:return
    data=(json.dumps(value,separators=(',',':'))+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
    try:os.write(fd,data)
    finally:os.close(fd)


def timed_generation(command, prompt, root, budget, append=False, elapsed_offset=0):
    """Timestamp events; budget=None permits an explicitly unbounded continuation."""
    try:
        from .l3_api_control import stopped
    except ImportError:
        from l3_api_control import stopped
    balance_stop=False
    start=time.monotonic(); active={}; spans=[]; errors=0; rc=None; timed_out=False; terminal_event=None
    with (root/'agent-events.jsonl').open('ab' if append else 'wb') as raw, (root/'agent-timeline.jsonl').open('a' if append else 'w') as timeline:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        proc.stdin.write(prompt);proc.stdin.close()
        selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
        pending=b''
        def event(line):
            nonlocal errors, terminal_event
            try:value=json.loads(line)
            except (ValueError,UnicodeDecodeError):return
            if value.get('type') in {'turn.completed','turn.failed'}:terminal_event=value['type']
            timestamp=time.time();elapsed=elapsed_offset+time.monotonic()-start
            item=value.get('item') or {};kind=item.get('type')
            timeline.write(json.dumps({'received_unix':timestamp,'elapsed_seconds':elapsed,'event':value})+'\n');timeline.flush()
            if value.get('type')=='error':errors+=1
            if kind=='command_execution':
                key=item.get('id')
                if value.get('type')=='item.started':active[key]=elapsed
                elif value.get('type')=='item.completed':
                    began=active.pop(key,None)
                    spans.append({'item_id':key,'started_seconds':began,'ended_seconds':elapsed,
                                  'elapsed_seconds':elapsed-began if began is not None else None,
                                  'exit_code':item.get('exit_code')})
        try:
            while True:
                if stopped():balance_stop=True;proc.kill();break
                remaining=None if budget is None else budget-(time.monotonic()-start)
                if remaining is not None and remaining<=0:timed_out=True;proc.kill();break
                ready=selector.select(1 if remaining is None else min(remaining,1))
                if ready:
                    chunk=os.read(proc.stdout.fileno(),65536)
                    if not chunk:break
                    raw.write(chunk);raw.flush();pending+=chunk
                    while b'\n' in pending:
                        line,pending=pending.split(b'\n',1);event(line)
                elif proc.poll() is not None:break
            if pending:event(pending)
            rc=proc.wait(timeout=10)
        finally:
            selector.close()
            if proc.poll() is None:proc.kill();proc.wait()
            proc.stdout.close()
    report={'generation_status':'api_balance_exhausted' if balance_stop else 'timeout' if timed_out else ('completed' if rc==0 and terminal_event=='turn.completed' else 'process_error'),
            'return_code':rc,'terminal_event':terminal_event,'elapsed_seconds':time.monotonic()-start,'model_error_events':errors,
            'tool_spans':spans,'unfinished_tool_ids':list(active),'timing_basis':'host receipt of Codex JSON events; tool intervals may overlap'}
    (root/'generation-timing.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def summarize_requests(path, stage='generation'):
    rows=[]
    if path.exists():
        for line in path.read_text().splitlines():
            try:rows.append(json.loads(line))
            except ValueError:pass
    starts={r['attempt_id']:r for r in rows if r.get('event')=='request_started' and r.get('stage')==stage}
    done={r['attempt_id']:r for r in rows if r.get('event')=='request_finished' and r.get('attempt_id') in starts}
    usage=[];seen=set()
    for r in done.values():
        if not r.get('usage'):continue
        key=r.get('response_id') or r['attempt_id']
        if key in seen:continue
        seen.add(key);usage.append(r['usage'])
    keys=['input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens','total_tokens']
    return {'stage':stage,'requests_started':len(starts),'requests_finished':len(done),
            'requests_failed_http':sum((r.get('http_status') or 0)>=400 for r in done.values()),
            'requests_without_usage':sum(not r.get('usage') for r in done.values())+len(starts)-len(done),
            'usage_coverage':'complete' if starts and len(done)==len(starts) and all(r.get('usage') for r in done.values()) else 'partial_or_unavailable',
            'reported_tokens':{k:sum(u[k] for u in usage if u.get(k) is not None) if any(u.get(k) is not None for u in usage) else None for k in keys},
            'request_elapsed_seconds_sum':sum(r.get('elapsed_seconds',0) for r in done.values()),
            'failed_http_elapsed_seconds_sum':sum(r.get('elapsed_seconds',0) for r in done.values() if (r.get('http_status') or 0)>=400),
            'notes':'Reported tokens exclude unknown usage. Cached input is a subset of input; reasoning output is a subset of output. Request durations can overlap and are not additive with tool or wall time.'}
