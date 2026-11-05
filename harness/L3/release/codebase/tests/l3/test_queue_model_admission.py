import copy
import pytest
from tools.add_l3_model_to_queue import extend_batch
from tools.continue_l3_suite import choose_next

def batch():
    return {'total_runs':4,'runs':[{'id':key+'-'+slug,'task_key':key,'task_path':'tasks/'+key,
      'model':'gpt-6-'+slug,'package_manifest_sha256':key+'-hash','status':'not_started',
      'output':'data/batch/'+key+'/'+slug} for key in ['l3-g02','l3-e01'] for slug in ['luna','astra']]}

def test_append_sol_preserves_inputs_existing_runs_and_is_idempotent():
    original=batch();before=copy.deepcopy(original)
    extended,added=extend_batch(original,'gpt-6-sol')
    assert original==before and extended['runs'][:4]==original['runs']
    assert extended['total_runs']==6 and len(added)==2
    for row in added:
        assert row['model']=='gpt-6-sol' and row['reasoning_effort']=='high'
        assert row['output'].endswith('/sol')
        assert row['package_manifest_sha256']==row['task_key']+'-hash'
    repeated,again=extend_batch(extended,'gpt-6-sol')
    assert repeated==extended and again==[]

def test_conflicting_input_packages_and_duplicate_ids_are_rejected():
    value=batch();value['runs'][1]['package_manifest_sha256']='wrong'
    with pytest.raises(ValueError,match='Mismatched'):extend_batch(value,'gpt-6-sol')
    value=batch();value['runs'].append(copy.deepcopy(value['runs'][0]))
    with pytest.raises(ValueError,match='Duplicate'):extend_batch(value,'gpt-6-sol')

def test_sol_uses_idle_slot_but_keeps_parked_luna_slot_priority():
    pending=['luna','sol'];byid={'luna':{'model':'gpt-6-luna'},'sol':{'model':'gpt-6-sol'}}
    assert choose_next(pending,byid,{'luna':0},9)=='sol'
    assert choose_next(pending,byid,{'luna':0},0)=='luna'


def test_include_minecraft_only_for_requested_model():
    existing,_=extend_batch(batch(),'gpt-6-sol')
    extra={'task_key':'l3-g01','task_path':'tasks/L3/MinecraftVillageOpenWorld',
           'package_manifest_sha256':'mc-hash','output':'data/batch/l3-g01/template'}
    extended,added=extend_batch(existing,'gpt-6-sol',[extra])
    assert [r['id'] for r in added]==['l3-g01-sol']
    assert extended['runs'][:-1]==existing['runs']
    assert added[0]['output']=='data/batch/l3-g01/sol'
    assert added[0]['reasoning_effort']=='high'
    assert extend_batch(extended,'gpt-6-sol',[extra])==(extended,[])
