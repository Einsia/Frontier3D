"""Export only this campaign's final reports; missing scores remain absent."""
from pathlib import Path
import csv
import hashlib
import json
import math
import statistics


def export_scores(output):
    output=Path(output);rows=[]
    statefile=output/"benchmark.json"
    campaign=json.loads((output/'campaign.json').read_text()) if (output/'campaign.json').is_file() else {}
    states=json.loads(statefile.read_text()).get("tasks",{}) if statefile.exists() else {}
    for file in sorted((output/"main_results").rglob("report.json")):
        r=json.loads(file.read_text())
        if states.get(r.get("task_id"),{}).get("status")=="technical_failure":continue
        from benchmark.engine import report_receipt, verify_generated, verify_report
        receipt = report_receipt(output, file.parent.name)
        if receipt.is_file():
            if hashlib.sha256(file.read_bytes()).hexdigest() != json.loads(receipt.read_text())['report_sha256']:
                raise ValueError('Accepted evaluation report changed')
            verify_generated(json.loads((receipt.parent / 'generate-result.json').read_text()))
            verify_report(output, r['task_id'], r['model'])
        if r.get("method_version")=="l3-perceptual-quality-v5":
            from benchmark.l3 import validate_report
            validate_report(r,output)
        value=r.get("S_core")
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):continue
        rows.append(dict(model=r["model"],effort=r.get('reasoning_effort') or campaign.get('reasoning_effort') or 'max',task_id=r["task_id"],S_core=r["S_core"],
                         score_valid=r.get("score_valid"),status=r.get("status"),
                         method=r.get("method_version"),report=str(file),
                         report_sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    with (output/"scores.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,list(rows[0]) if rows else ["model","task_id","S_core"]);w.writeheader();w.writerows(rows)
    summary={"completed":len(rows),"mean":statistics.fmean(r["S_core"] for r in rows) if rows else None}
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    # The weighted total requires all145 valid task scores.
    from benchmark.aggregation import load_policy,export
    active={t for c in load_policy()['categories'] for t in c['tasks']}
    scored=[{'model':r['model'],'effort':r['effort'],'task_id':r['task_id'],'score_100':r['S_core']*100}
            for r in rows if r['task_id'] in active and r['score_valid'] is not False and r['status'] not in ('system_invalid','failed','error','technical_failure')]
    export(scored,output)
    return summary
