"""Read-only accounting report from a single trial's durable transport/tool events."""
import argparse
import json
import re
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.l3_usage import summarize_requests

def rows(path):
    result=[]
    if path.exists():
        for line in path.read_text().splitlines():
            try:result.append(json.loads(line))
            except ValueError:pass
    return result

def interval_union(intervals):
    merged=[]
    for a,b in sorted(intervals):
        if b<a:continue
        if merged and a<=merged[-1][1]:merged[-1][1]=max(merged[-1][1],b)
        else:merged.append([a,b])
    return sum(b-a for a,b in merged)

def report(root, now=None):
    now=time.time() if now is None else now
    trial=json.loads((root/'trial.json').read_text());started=trial.get('started_unix')
    finished=trial.get('finished_unix');end=finished if finished is not None else now
    ledger=rows(root/'model-requests.jsonl')
    starts={x['attempt_id']:x for x in ledger if x.get('event')=='request_started' and x.get('stage')=='generation' and x.get('path','/v1/responses')=='/v1/responses'}
    ends={x['attempt_id']:x for x in ledger if x.get('event')=='request_finished' and x.get('attempt_id') in starts}
    failed=[x for x in ends.values() if x.get('terminal_event')=='response.failed' or (x.get('http_status') or 0)>=400]
    intervals=[]
    for key,x in starts.items():
        if started is not None:intervals.append((max(started,x['started_unix']),min(end,ends.get(key,{}).get('finished_unix',end))))
    events=rows(root/'agent-events.jsonl')
    commands=[x['item'] for x in events if x.get('type')=='item.completed' and x.get('item',{}).get('type')=='command_execution']
    turns=[x.get('usage') for x in events if x.get('type')=='turn.completed' and isinstance(x.get('usage'),dict)]
    builds=[]
    for path in (root/'workspace/checks').glob('*/build.log'):
        if path.parent.name.startswith('preflight'):continue
        text=path.read_text(errors='replace')
        elapsed=re.findall(r'Total execution time:\s*([0-9.]+)\s*seconds',text)
        result=re.findall(r'Result:\s*([^\n]+)',text)
        builds.append({'directory':str(path.parent.relative_to(root)),'cpp_elapsed_seconds':float(elapsed[-1]) if elapsed else None,
                       'result':result[-1].strip() if result else 'unfinished_or_not_reported'})
    return {'model':trial.get('model'),'trial':str(root),'status':trial.get('status'),
            'generation_started_unix':started,'generation_finished_unix':finished,
            'generation_wall_seconds':max(0,end-started) if started is not None else None,
            'budget_seconds':trial.get('budget_seconds'),'generation_outcome':trial.get('generation_status'),
            'request_count':len(starts),'completed_response_count':sum(x.get('terminal_event')=='response.completed' for x in ends.values()),
            'failed_response_count':len(failed),'pending_request_count':len(starts)-len(ends),
            'request_occupied_wall_seconds':interval_union(intervals),
            'failed_request_seconds_sum':sum(x.get('elapsed_seconds',0) for x in failed),
            'codex_error_events':sum(x.get('type')=='error' for x in events),
            'completed_command_count':len(commands),'failed_command_count':sum(x.get('exit_code') not in [None,0] for x in commands),
            'completed_file_change_count':sum(x.get('type')=='item.completed' and x.get('item',{}).get('type')=='file_change' for x in events),
            'provider_usage':summarize_requests(root/'model-requests.jsonl'),
            'codex_completed_turn_usage':turns,'builds':builds,'formal_score':None,
            'notes':['Environment setup/preflight and independent evaluation are outside generation_wall_seconds.',
                     'Generation includes API requests, retries, agent edits, builds and previews; the budget is not reset.',
                     'Provider counters and Codex counters are separate cross-checks and must not be added together.',
                     'Cached input is included in input tokens; reasoning output is included in output tokens.',
                     'Unknown usage remains unknown. Timing categories can overlap; failed_request_seconds_sum excludes retry backoff.',
                     'A post-terminal BrokenPipeError with response.completed records client closure, not a failed model response.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--output',type=Path)
    a=p.parse_args();value=report(a.trial.resolve());text=json.dumps(value,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    else:print(text)
