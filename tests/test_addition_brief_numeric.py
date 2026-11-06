import pytest

from src.evaluator.addition_brief_numeric import numeric_data_score


def measure(status):
    plan={'task_id':'fixture','native_content_checks':[{'id':'a'},{'id':'b'}]}
    report={'status':'audited','case_id':'fixture',
            'requirements':[{'id':'a','status':'satisfied'},{'id':'b','status':status}]}
    return numeric_data_score(report,plan)


def test_unavailable_numeric_measurement_blocks_component_without_dropping_denominator():
    result=measure('not_measurable')
    assert result['status']=='not_measurable' and result['score'] is None
    assert result['checks']==2 and result['missing_checks']==['b']
    assert result['unresolved']==['b']


@pytest.mark.parametrize('status',['violated','partial','observed'])
def test_measured_non_demonstration_keeps_zero_credit_in_fixed_denominator(status):
    result=measure(status)
    assert result['status']=='measured' and result['score']==.5
    assert result['checks']==2 and result['missing_checks']==[]


def test_all_satisfied_receives_full_credit():
    assert measure('satisfied')['score']==1
