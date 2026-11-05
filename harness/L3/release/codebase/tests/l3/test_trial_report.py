import json
from tools.report_l3_trial import report, count_checks
from harness.L3.MinecraftVillage.protocol import REQUIRED, tree_digest

def test_unmeasured_targets_never_become_failed_or_passed_scores(tmp_path):
    (tmp_path/'trial.json').write_text(json.dumps({'status':'generating','model':'gpt-5.6-luna'}))
    value=report(tmp_path)
    targets=value['deterministic']['interaction']['targets']
    assert set(targets)==set(REQUIRED)
    assert all(t['status']=='not_measured' and t['formal_score'] is None for t in targets.values())
    assert value['formal_score'] is None
    assert value['rubrics']['score'] is None

def test_contract_failure_and_false_assertion_remain_distinct(tmp_path):
    (tmp_path/'trial.json').write_text(json.dumps({'status':'generation_incomplete_candidate_frozen','model':'gpt-5.6-luna'}))
    project=tmp_path/'workspace/project';project.mkdir(parents=True)
    run=tmp_path/'verification';run.mkdir()
    (run/'run.json').write_text(json.dumps({
        'status':'measured','source_sha256':tree_digest(project),
        'submission_contract_failures':{'house01_door':{'status':'submission_contract_failure'}},
        'episodes':{'house02_door':{'completed':True,'diagnostics':{'checks':{'visible':True,'opens':False,'clearance':None}}}}}))
    targets=report(tmp_path)['deterministic']['interaction']['targets']
    assert targets['house01.door']['status']=='submission_contract_failure'
    assert targets['house02.door']['status']=='measured'
    assert targets['house02.door']['check_counts']=={'passed':1,'failed':1,'unresolved':1,'total':3}
