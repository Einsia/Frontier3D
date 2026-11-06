"""Active task identities, score scale and complete category-weight aggregation."""
import json

import pytest

from benchmark.aggregation import aggregate, load_policy, normalized_rows
from benchmark.resources import ROOT


def full_rows():
    policy=load_policy()
    return [{'model':'fixture','task_id':t,'score_100':40+10*int(c['level'][1:])} for c in policy['categories'] for t in c['tasks']]

def test_levels_and_categories_match_the_adopted_arithmetic_mean_scheme():
    policy=load_policy();categories={c['key']:c for c in policy['categories']}
    assert policy['task_count']==145
    assert [policy['levels'][l]['tasks'] for l in ['L1','L2','L3']]==[65,65,15]
    assert 'L1/CodeEdit' not in categories
    for c in categories.values():
        settings=policy['levels'][c['level']]
        assert c['weight']==pytest.approx(settings['weight']*c['task_count']/settings['tasks'])
    row=aggregate(full_rows())[0]
    assert row['L1_score_100']==pytest.approx(50)
    assert row['L2_score_100']==pytest.approx(60)
    assert row['L3_score_100']==pytest.approx(70)
    assert row['total_100']==pytest.approx(.3*50+.3*60+.4*70)

def test_missing_level_task_blocks_total_without_renormalization():
    rows=full_rows();missing=next(r for r in rows if r['task_id'].startswith('L3/'))
    rows.remove(missing);row=aggregate(rows)[0]
    assert row['completed']==144 and row['status']=='incomplete'
    assert row['total_100'] is None and row['L3_score_100'] is None
    assert row['L1_score_100']==pytest.approx(50) and row['L2_score_100']==pytest.approx(60)

def test_duplicates_and_nonfinite_scores_are_rejected():
    rows=full_rows()
    with pytest.raises(ValueError,match='Duplicate'):aggregate(rows+[rows[0]])
    with pytest.raises(ValueError,match='Invalid score'):aggregate([{**rows[0],'score_100':float('nan')}])

def test_explicit_legacy_namespace_avoids_colliding_numbered_tasks(tmp_path):
    mapping=json.loads((ROOT/'configs/release/task-id-map.json').read_text())['tasks']
    record=next(r for r in mapping if r['old_task_id']=='L1/Image2Code/task_L1_Image2Code_018')
    assert record['new_task_id']=='L1/Image2Code/task_L1_Image2Code_016'
    path=tmp_path/'old.csv'
    path.write_text('model,effort,task_id,S_core\nfixture,max,'+record['old_task_id']+',0.5\n')
    assert normalized_rows([path],identity='source')[0]['task_id']==record['new_task_id']
    assert normalized_rows([path],identity='release')[0]['task_id']==record['old_task_id']

def test_l3_harbor_scores_map_to_the_continuous_release_ids(tmp_path):
    path=tmp_path/'l3.csv';path.write_text('model,effort,task_key,score_100\nfixture,max,l3-e01,60\nqwen,xhigh,l3-e01,20\n')
    rows=normalized_rows([path])
    assert rows==[{'model':'fixture','task_id':'L3/Image2Environment/task_L3_Image2Environment_001','score_100':60.},
                  {'model':'qwen','effort':'xhigh','task_id':'L3/Image2Environment/task_L3_Image2Environment_001','score_100':20.}]


def test_effort_groups_never_mix_and_confirmed_delivery_zero_is_included(tmp_path):
    path=tmp_path/'efforts.csv'
    path.write_text('model,effort,task_key,score_100,status,score_valid\nqwen3.8-max,xhigh,l3-e01,40,measured,true\nqwen3.8-max,max,l3-e01,60,measured,true\nqwen3.8-max,xhigh,l3-e02,0,system_invalid,false\n')
    results=aggregate(normalized_rows([path]))
    assert {(r['effort'],r['completed']) for r in results}=={('max',1),('xhigh',2)}
    assert all(r['total_100'] is None for r in results)


def test_export_and_csv_reaggregation_keep_delivery_zero_in_145_task_mean(tmp_path):
    from benchmark.export import export_scores
    rows=full_rows()
    failed=rows[0]['task_id']
    for row in rows:
        report={'model': row['model'], 'task_id': row['task_id'],
                'S_core': 0 if row['task_id']==failed else row['score_100']/100,
                'status': 'system_invalid' if row['task_id']==failed else 'scored',
                'score_valid': row['task_id']!=failed}
        target=tmp_path/'main_results'/row['model']/row['task_id'].split('/')[-1]/'report.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(report))
    assert export_scores(tmp_path)['completed']==145
    direct=json.loads((tmp_path/'weighted-summary.json').read_text())['models'][0]
    replay=aggregate(normalized_rows([tmp_path/'scores.csv']))[0]
    assert direct['status']==replay['status']=='complete'
    assert direct['L1_score_100']==replay['L1_score_100']==pytest.approx(64*50/65)
    assert direct['total_100']==replay['total_100']==pytest.approx(.3*(64*50/65)+.3*60+.4*70)


@pytest.mark.parametrize('status',['technical_failure','infrastructure_error','not_measurable','error','failed'])
def test_technical_zero_never_becomes_a_measured_delivery_zero(tmp_path,status):
    from benchmark.export import export_scores
    task=full_rows()[0]['task_id']
    report={'model':'fixture','task_id':task,'S_core':0,'status':status,'score_valid':False}
    target=tmp_path/'main_results/fixture/task/report.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(report))
    assert export_scores(tmp_path)['completed']==0
    assert normalized_rows([tmp_path/'scores.csv'])==[]
    assert aggregate([{'model':'fixture','task_id':task,'score_100':0,'status':status,'score_valid':False}])==[]


def test_system_invalid_positive_score_is_rejected(tmp_path):
    path=tmp_path/'bad.csv'
    path.write_text('model,task_key,score_100,status,score_valid\nfixture,l3-e01,20,system_invalid,false\n')
    with pytest.raises(ValueError,match='retain zero'):
        normalized_rows([path])

def test_active_numbers_are_continuous_and_all_paths_exist():
    mapping=json.loads((ROOT/'configs/release/task-id-map.json').read_text())['tasks']
    assert len(mapping)==145 and len({r['new_task_id'] for r in mapping})==145
    assert [r['release_number'] for r in mapping]==list(range(1,146))
    for row in mapping:assert (ROOT/row['proposed_public_directory']/'task.toml').is_file()
    for cat in ['Image2Code','Image2Code-SingleView','Reference2Scene-RealPhoto']:
        rows=[r for r in mapping if r['category']==cat]
        assert len(rows)==25
        assert sorted(int(r['new_task_id'][-3:]) for r in rows)==list(range(1,26))


def test_aggregation_cli_rejects_legacy_task_ids_when_namespace_is_source(tmp_path):
    path=tmp_path/'old.csv'
    path.write_text('model,effort,task_id,S_core\nfixture,max,L1/Image2Code/task_L1_Image2Code_017,0.5\n')
    with pytest.raises(ValueError,match='outside the active release'):
        normalized_rows([path],identity='source')


def test_unequal_category_sizes_use_task_means_and_retired_codeedit_is_rejected():
    rows=full_rows()
    for r in rows:
        if r['task_id'].startswith('L1/'):
            r['score_100']=100 if '/Text2Code/' in r['task_id'] else 0
        elif r['task_id'].startswith('L3/'):
            r['score_100']=100 if r['task_id'] in {c['tasks'][0] for c in load_policy()['categories'] if c['level']=='L3'} else 0
    result=aggregate(rows)[0]
    assert result['L1_score_100']==pytest.approx(15*100/65)
    assert result['L3_score_100']==pytest.approx(2*100/15)
    assert result['total_100']==pytest.approx(.3*(15*100/65)+.3*60+.4*(2*100/15))
    with pytest.raises(ValueError,match='Unknown model or task'):
        aggregate([*rows,{'model':'fixture','task_id':'L1/CodeEdit/task_L1_CodeEdit_001','score_100':100}])


def test_old_l3_wrapper_ids_require_the_explicit_source_namespace(tmp_path):
    path=tmp_path/'old-l3.csv'
    path.write_text('model,effort,task_id,score_100\nfixture,max,L3/Unified/task_L3_Unified_007,60\n')
    assert normalized_rows([path],identity='source')[0]['task_id']=='L3/Image2Environment/task_L3_Image2Environment_005'
    with pytest.raises(ValueError,match='outside the active release'):
        normalized_rows([path],identity='release')
