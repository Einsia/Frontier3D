"""Frozen task population, arithmetic level means and explicit coverage checks."""
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
POLICY_PATH=ROOT/'configs/release/aggregation-policy.json'

def score_is_complete(row, value):
    """A confirmed delivery zero is measured; technical missingness is not."""
    if type(value) not in (int, float) or not math.isfinite(value):
        return False
    if not 0 <= value <= 100:
        raise ValueError('Invalid score')
    status = row.get('status')
    if status == 'system_invalid':
        if value != 0 or row.get('score_valid') in (True, 'true', 'True'):
            raise ValueError('Confirmed delivery failure must retain zero and invalid delivery status')
        return True
    if status in {'failed', 'error', 'technical_failure', 'infrastructure_error',
                  'not_measurable', 'not_implemented'}:
        return False
    return row.get('score_valid') not in (False, 'false', 'False')


def load_policy():
    policy=json.loads(POLICY_PATH.read_text())
    tasks=[t for c in policy['categories'] for t in c['tasks']]
    if len(tasks)!=policy['task_count'] or len(set(tasks))!=len(tasks):
        raise ValueError('Aggregation task population is inconsistent')
    if not math.isclose(sum(c['weight'] for c in policy['categories']),1,abs_tol=1e-12):
        raise ValueError('Aggregation weights must sum to one')
    for level,settings in policy['levels'].items():
        group=[c for c in policy['categories'] if c['level']==level]
        if sum(c['task_count'] for c in group)!=settings['tasks'] or not math.isclose(sum(c['weight'] for c in group),settings['weight'],abs_tol=1e-12):
            raise ValueError('Level aggregation population or weight is inconsistent')
        if policy.get('level_aggregation')=='arithmetic_mean':
            for category in group:
                expected=settings['weight']*category['task_count']/settings['tasks']
                if not math.isclose(category['weight'],expected,abs_tol=1e-12):
                    raise ValueError('Category weights disagree with arithmetic level means')
    return policy

def normalized_rows(files,identity='release'):
    """Explicit namespaces prevent old numeric IDs colliding with new task IDs."""
    if identity not in {'release','source'}:raise ValueError('Unknown identity namespace')
    mapping=json.loads((ROOT/'configs/release/task-id-map.json').read_text())['tasks']
    source={alias:r['new_task_id'] for r in mapping
            for alias in [r['old_task_id'], *r.get('legacy_task_ids', [])]}
    harbor={r['harbor_key']:r['new_task_id'] for r in mapping if r.get('harbor_key')}
    allowed={r['new_task_id'] for r in mapping}
    rows=[]
    for file in files:
        with Path(file).open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                tid=r.get('task_id') or r.get('task_key') or r.get('task')
                if tid in harbor:tid=harbor[tid]
                elif identity=='source':tid=source.get(tid)
                if tid not in allowed:
                    raise ValueError('Task is outside the active release: '+str(tid))
                raw=r.get('score_100')
                value=float(raw) if raw not in (None,'') else float(r['S_core'])*100 if r.get('S_core') not in (None,'') else None
                if value is None:continue
                if r.get('S_core') not in (None,'') and not math.isclose(value,float(r['S_core'])*100,abs_tol=1e-9):
                    raise ValueError('Score scales disagree')
                model=r.get('model') or r.get('model_id')
                from src.generator.harnesses import model_effort
                effort=r.get('effort') or model_effort(model)
                if effort not in ('medium','high','xhigh','max'):raise ValueError('Invalid effort')
                if not score_is_complete(r, value):continue
                item={'model':model,'task_id':tid,'score_100':value}
                if effort!='max' or model_effort(model)!='max':item['effort']=effort
                rows.append(item)
    return rows

def aggregate(rows,policy=None):
    policy=policy or load_policy();population={t for c in policy['categories'] for t in c['tasks']};by_model={}
    for r in rows:
        if not r.get('model') or r['task_id'] not in population:raise ValueError('Unknown model or task identity')
        value=r['score_100']
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=100:raise ValueError('Invalid score')
        if not score_is_complete(r, value):continue
        from src.generator.harnesses import model_effort
        effort=r.get('effort') or model_effort(r['model'])
        bucket=by_model.setdefault((r['model'],effort),{})
        if r['task_id'] in bucket:raise ValueError('Duplicate model/task score: '+r['model']+' '+r['task_id'])
        bucket[r['task_id']]=value
    output=[]
    for (model,effort),scores in by_model.items():
        result={'model':model,'effort':effort,'policy_version':policy['version'],'completed':len(scores),'expected':policy['task_count']}
        categories={};contributions={}
        for c in policy['categories']:
            values=[scores[t] for t in c['tasks'] if t in scores]
            complete=len(values)==c['task_count']
            mean=sum(values)/len(values) if complete else None
            categories[c['key']]={'completed':len(values),'expected':c['task_count'],'mean_100':mean,'weight':c['weight'],'weighted_contribution':mean*c['weight'] if mean is not None else None}
        for level,settings in policy['levels'].items():
            selected=[categories[c['key']] for c in policy['categories'] if c['level']==level]
            complete=all(c['weighted_contribution'] is not None for c in selected)
            if complete and policy.get('level_aggregation')=='arithmetic_mean':
                tasks=[t for c in policy['categories'] if c['level']==level for t in c['tasks']]
                level_score=sum(scores[t] for t in tasks)/settings['tasks']
                contribution=level_score*settings['weight']
            else:
                contribution=sum(c['weighted_contribution'] for c in selected) if complete else None
            result[level+'_completed']=sum(c['completed'] for c in selected)
            result[level+'_expected']=settings['tasks']
            result[level+'_score_100']=(level_score if policy.get('level_aggregation')=='arithmetic_mean'
                                      else contribution/settings['weight']) if contribution is not None else None
            result[level+'_contribution']=contribution
            contributions[level]=contribution
        result['total_100']=sum(contributions.values()) if all(v is not None for v in contributions.values()) else None
        result['status']='complete' if result['total_100'] is not None else 'incomplete'
        result['categories']=categories;output.append(result)
    output.sort(key=lambda r:(r['total_100'] is None,-(r['total_100'] or 0),r['model'],r['effort']))
    for i,row in enumerate(output,1):row['rank']=i if row['total_100'] is not None else None
    return output

def export(rows,output,policy=None):
    policy=policy or load_policy();results=aggregate(rows,policy);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    fields=['rank','model','effort','L1_score_100','L2_score_100','L3_score_100','total_100','L1_contribution','L2_contribution','L3_contribution','L1_completed','L1_expected','L2_completed','L2_expected','L3_completed','L3_expected','completed','expected','status','policy_version']
    with (output/'leaderboard.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(results)
    document={'version':policy['version'],'policy_sha256':hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),'policy':policy,'models':results}
    (output/'weighted-summary.json').write_text(json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return results
