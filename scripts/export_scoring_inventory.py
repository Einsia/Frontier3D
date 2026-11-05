"""Export the public checkout's task scoring contracts; no tasks/API calls run."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.evaluator.legacy_detail_v2 import COMPONENT_RULES, VERSION

FROZEN = ROOT/'configs/release'


def read(path):
    return json.loads(Path(path).read_text())


def relative(path):
    return str(Path(path).relative_to(ROOT))


def resource_path(token):
    if token.startswith('@resource/'):
        return FROZEN/token.removeprefix('@resource/')
    if token.startswith('@repo/'):
        return ROOT/token.removeprefix('@repo/')
    raise ValueError('Expected a release-owned path token')


def binding(path):
    with Path(path).open('rb') as stream:
        return {'path':relative(path), 'sha256':hashlib.file_digest(stream,'sha256').hexdigest()}


def main():
    methods = {r['id']:r for r in read(FROZEN/'published-methods.json')}
    recipes = {r['task_id']:r for r in read(FROZEN/'legacy-policy.json')['cases']}
    populations = read(FROZEN/'detail-populations.json')
    rows = []
    for file in sorted((ROOT/'data/3dbench/tasks').glob('L[12]/*/*/task.toml')):
        task = tomllib.loads(file.read_text())
        tid = task['id']; name = file.parent.name
        native = task.get('harness_status') in {'mvp','implemented'}
        config = FROZEN/('linear-config/'+tid if native else 'addition-config/'+name)
        final = read(config/('rule.json' if native else 'plan.json'))
        row = {'task_id':tid, 'title':task['title'], 'level':task['level'], 'category':task['category'],
            'route':'native' if native else 'extension', 'scoring_version':VERSION,
            'baseline_method':methods[tid]['method_version'] if native else 'new-task-extension',
            'final_weights':final['weights'], 'weight_contract':binding(config/('rule.json' if native else 'plan.json')),
            'task_manifest':relative(file), 'task_instruction':relative(file.parent/'instruction.md')}
        if native:
            spec = read(file.parent/'harness/eval_spec.json')
            row['native_spec'] = binding(file.parent/'harness/eval_spec.json')
            checks = spec.get('checks',{})
            row['native_checks'] = [{'module':group,**check} for group,items in checks.items() for check in items]
            row['native_tolerances'] = spec.get('tolerances',{})
            row['execution_seeds'] = spec.get('seeds',[])
            if task['category']=='CodeEdit':
                row['edit_quality_groups'] = spec.get('l1_edit_quality',{})
                row['detail_method']='keep_legacy';row['detail_variants']=[];row['detail_criteria']=[]
                row['baseline_judge'] = None
            else:
                recipe=recipes[tid]; plan=resource_path(recipe['source_plan']['path'])
                detail_spec=plan.with_name('judge_spec.json')
                row['detail_method']=recipe['method']
                row['detail_recipe']=dict(recipe)
                row['detail_plan']=binding(plan)
                row['detail_judge_spec']=binding(detail_spec)
                row['detail_criteria']=recipe['criteria']
                row['detail_variants']=populations[tid]
                baseline = (FROZEN/'l1-plans'/tid/'vlm_spec.json' if task['level']==1
                            else file.parent/'harness/vlm_spec.json')
                row['baseline_judge']={'binding':binding(baseline),**read(baseline)}
                if task['level']==1:
                    aligned=read(baseline.with_name('alignment.json'))
                    row['automatic_content_checks']=aligned.get('automatic_checks',[])
        else:
            plan=read(config/'plan.json')
            baseline=config/'vlm_spec.json';detail=config/'detail_spec.json'
            row['baseline_judge']={'binding':binding(baseline),**read(baseline)}
            row['detail_method']='extension-visual-subset-minimum'
            row['detail_plan']=binding(config/'plan.json')
            row['detail_judge_spec']=binding(detail)
            row['detail_criteria']=read(detail)['checks']
            row['detail_variants']=plan['detail_variants']
            row['native_content_checks']=plan['native_content_checks']
            row['execution_seeds']=[0,1,2]
            row['rules']=plan['rules']
        row['final_override']=None
        if tid in COMPONENT_RULES:
            row['final_override']={'revision':'direct-components-linear-r2',
                'component_rules':COMPONENT_RULES[tid], 'preserved_components':['localization'],
                'aggregation':'q=coverage*(1-deviation); no ordinary detail minimum for the final replacement'}
        assert abs(sum(row['final_weights'].values())-1)<1e-10
        rows.append(row)
    assert len(rows)==130 and len({r['task_id'] for r in rows})==130
    doc={'schema':'public-scoring-contract-inventory-v1','scoring_version':VERSION,
         'scope':'130 L1/L2 task IDs present in this public checkout; no candidate results',
         'counts':{'tasks':len(rows),'routes':dict(Counter(r['route'] for r in rows)),
                   'categories':dict(Counter(r['category'] for r in rows))},'tasks':rows}
    out=ROOT/'docs/reference/scoring-task-inventory.json'
    out.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n')
    fields=['task_id','title','route','baseline_method','final_weights','baseline_judge_protocol',
            'detail_method','detail_variant_count','detail_variants','final_override','weight_contract']
    with out.with_suffix('.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fields);w.writeheader()
        for row in rows:
            w.writerow({k:row[k] for k in fields if k in row and k not in {'final_weights','detail_variants','final_override','weight_contract'}}|
                {'final_weights':json.dumps(row['final_weights'],ensure_ascii=False,sort_keys=True),
                 'baseline_judge_protocol':(row['baseline_judge'] or {}).get('protocol','none'),
                 'detail_variant_count':len(row['detail_variants']),
                 'detail_variants':';'.join(row['detail_variants']),
                 'final_override':row['final_override']['revision'] if row['final_override'] else '',
                 'weight_contract':row['weight_contract']['path']})
    print(json.dumps(doc['counts'],ensure_ascii=False))


if __name__=='__main__':
    main()
