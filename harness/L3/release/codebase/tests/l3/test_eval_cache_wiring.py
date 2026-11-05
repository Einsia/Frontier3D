import json
import pytest
from tools.l3_eval_cache import configured_cache,seed_evaluation_cache
from harness.L3.MinecraftVillage.protocol import digest

def setup_cache(tmp_path,monkeypatch):
    batch=tmp_path/'batch';batch.mkdir()
    cache=batch/'cache';cache.mkdir();(cache/'shader').write_bytes(b'organizer shader')
    manifest=batch/'manifest.json'
    manifest.write_text(json.dumps({'provenance':'organizer_preflight','captured_before_candidate_generation':True,'files':{'shader':digest(cache/'shader')}}))
    config={'source':str(cache),'manifest':str(manifest),'manifest_sha256':digest(manifest)}
    (batch/'settings.json').write_text(json.dumps({'evaluation_trusted_cache':config}))
    monkeypatch.setenv('L3_EXPERIMENT_BATCH',str(batch))
    return batch,cache,manifest,config

def test_nonbatch_behavior_unchanged(monkeypatch,tmp_path):
    monkeypatch.delenv('L3_EXPERIMENT_BATCH',raising=False)
    assert configured_cache() is None
    assert seed_evaluation_cache(tmp_path/'unused') is None
    assert not (tmp_path/'unused').exists()

def test_verified_seed_is_an_independent_copy(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    dest=batch/'fresh'
    record=seed_evaluation_cache(dest)
    assert record['manifest_sha256']==digest(manifest)
    assert record['file_count']==1 and record['provenance']=='organizer_preflight'
    (dest/'shader').write_bytes(b'local update')
    assert (cache/'shader').read_bytes()==b'organizer shader'

def test_manifest_mutation_rejected(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    manifest.write_text('{}')
    with pytest.raises(ValueError,match='manifest changed'):seed_evaluation_cache(batch/'fresh')

def test_cache_mutation_rejected(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    (cache/'shader').write_bytes(b'changed')
    with pytest.raises(ValueError,match='integrity'):seed_evaluation_cache(batch/'fresh')

def test_existing_cache_never_overwritten(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    dest=batch/'fresh';dest.mkdir();(dest/'existing').write_bytes(b'keep')
    with pytest.raises(ValueError,match='empty fresh'):seed_evaluation_cache(dest)
    assert (dest/'existing').read_bytes()==b'keep'

def test_outside_batch_cache_rejected(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    config['source']=str(tmp_path/'outside')
    (batch/'settings.json').write_text(json.dumps({'evaluation_trusted_cache':config}))
    with pytest.raises(ValueError,match='NVMe batch'):configured_cache()

def test_candidate_cache_not_accepted_even_with_matching_manifest_hash(tmp_path,monkeypatch):
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    info=json.loads(manifest.read_text());info['provenance']='candidate';manifest.write_text(json.dumps(info))
    config['manifest_sha256']=digest(manifest)
    (batch/'settings.json').write_text(json.dumps({'evaluation_trusted_cache':config}))
    with pytest.raises(ValueError,match='organizer preflight'):seed_evaluation_cache(batch/'fresh')


def test_prepared_workspace_seeds_only_cache_and_records_provenance(tmp_path,monkeypatch):
    from tools.l3_eval_cache import seed_prepared_evaluation_cache
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    folder=batch/'task';project=folder/'workspace/project';project.mkdir(parents=True)
    (project/'source.cpp').write_text('frozen candidate')
    result=seed_prepared_evaluation_cache(folder)
    assert result['seed_stage']=='prepared_before_engine_start'
    assert (folder/'workspace/.cache/ue/shader').read_bytes()==b'organizer shader'
    assert (project/'source.cpp').read_text()=='frozen candidate'
    assert json.loads((folder/'trusted-cache-seed.json').read_text())==result

@pytest.mark.parametrize('marker',['source.json','run.json','built.json','container-start.log',
                                  'workspace/build','workspace/episodes','verification'])
def test_started_workspace_is_not_seeded(tmp_path,monkeypatch,marker):
    from tools.l3_eval_cache import seed_prepared_evaluation_cache
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    folder=batch/'task';(folder/'workspace/project').mkdir(parents=True)
    p=folder/marker;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('keep')
    assert seed_prepared_evaluation_cache(folder) is None
    assert p.read_text()=='keep'
    assert not (folder/'workspace/.cache/ue').exists()

def test_prepared_nonempty_cache_is_preserved(tmp_path,monkeypatch):
    from tools.l3_eval_cache import seed_prepared_evaluation_cache
    batch,cache,manifest,config=setup_cache(tmp_path,monkeypatch)
    folder=batch/'task';(folder/'workspace/project').mkdir(parents=True)
    dest=folder/'workspace/.cache/ue';dest.mkdir(parents=True);(dest/'existing').write_text('keep')
    assert seed_prepared_evaluation_cache(folder) is None
    assert (dest/'existing').read_text()=='keep'
    assert not (dest/'shader').exists()
