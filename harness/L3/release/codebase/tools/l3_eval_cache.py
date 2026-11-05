"""Wire frozen organizer preflight DDC into fresh independent evaluators only."""
import json,os
from pathlib import Path
from harness.L3.MinecraftVillage.protocol import digest

def configured_cache():
    batch=os.environ.get('L3_EXPERIMENT_BATCH')
    if not batch:return None
    batch=Path(batch).resolve()
    settings=json.loads((batch/'settings.json').read_text())
    config=settings.get('evaluation_trusted_cache')
    if not config:return None
    source=Path(config['source']).resolve()
    manifest=Path(config['manifest']).resolve()
    if not source.is_relative_to(batch) or not manifest.is_relative_to(batch):
        raise ValueError('Evaluation cache must reside in this NVMe batch')
    if digest(manifest)!=config['manifest_sha256']:
        raise ValueError('Evaluation cache manifest changed')
    return source,manifest

def seed_evaluation_cache(destination):
    configured=configured_cache()
    if configured is None:return None
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Only empty fresh evaluator caches may be seeded')
    from tools.verify_l3_submission import seed_trusted_cache
    source,manifest=configured
    result=seed_trusted_cache(source,manifest,destination)
    return {**result,'source':str(source),'manifest':str(manifest)}


def seed_prepared_evaluation_cache(folder):
    """Seed an empty prepare-only workspace; never touch started UE evidence."""
    folder=Path(folder)
    if not (folder/'workspace/project').is_dir():return None
    markers=('source.json','run.json','built.json','container-start.log',
             'workspace/build','workspace/episodes','verification')
    if any((folder/name).exists() for name in markers):return None
    destination=folder/'workspace/.cache/ue'
    if destination.exists() and any(destination.iterdir()):return None
    result=seed_evaluation_cache(destination)
    if result:
        result={**result,'seed_stage':'prepared_before_engine_start'}
        (folder/'trusted-cache-seed.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
