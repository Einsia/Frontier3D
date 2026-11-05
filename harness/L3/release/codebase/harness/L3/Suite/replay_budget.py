"""Estimate retry wall time from a matching timed-out replay's measured progress."""
import json,math,re
from tools.capture_l3_algorithms import replay_timeout

def retry_budget(plan,episodes,kind,log_path,replay_folders=None):
    baseline=replay_timeout(plan);timeout=baseline;evidence=[]
    if not log_path.exists():return timeout,evidence
    matches=re.findall(r"timed out after ([0-9]+(?:\\.[0-9]+)?)s",log_path.read_text(errors='replace'))
    if not matches:return timeout,evidence
    previous=max(float(x) for x in matches)
    total=sum(max(0.,float(step.get('seconds',0))) for step in plan['steps'])
    archives=episodes.glob(kind+'-failed-*') if replay_folders is None else replay_folders
    for archive in archives:
        try:
            if json.loads((archive/'plan.json').read_bytes())!=plan:continue
            paths=sorted(archive.glob('trajectory_*.json'))
            if not paths:continue
            first=json.loads(paths[0].read_bytes());last=json.loads(paths[-1].read_bytes())
            progress=float(last['time'])-float(first['time'])
            if not math.isfinite(progress) or progress<=0:continue
            # Retry resource budget only; never edit simulation plans or scoring.
            estimate=math.ceil(previous*max(1.,total/progress)*1.5+900)
            timeout=max(timeout,estimate)
            evidence.append({'archive':str(archive),'observed_sim_seconds':progress,'previous_timeout_seconds':previous,'estimated_timeout_seconds':estimate})
        except (OSError,ValueError,KeyError,TypeError):continue
    return timeout,evidence
