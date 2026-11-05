"""Calibrate ground against pawn collision; retain frozen candidate and prior evidence."""
import json,shutil,subprocess,time
from pathlib import Path
from harness.L3.MinecraftVillage.protocol import tree_digest,read_json,write_json

MARKER='L3_GROUND_PAWN_QUERY_V1'
OLD='''        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(BenchSurfaceRay),true,Pawn);
        const bool Contact=GetWorld()->LineTraceSingleByChannel(Hit,ReadVec(S,TEXT("from_cm")),ReadVec(S,TEXT("to_cm")),ECC_Visibility,Params);'''
NEW='''        // L3_GROUND_PAWN_QUERY_V1: ground follows character collision, not visibility.
        const bool PawnGround=Str(S,TEXT("collision_channel"))==TEXT("pawn");
        FHitResult Hit;FCollisionQueryParams Params(SCENE_QUERY_STAT(BenchSurfaceRay),!PawnGround,Pawn);
        const bool Contact=GetWorld()->LineTraceSingleByChannel(Hit,ReadVec(S,TEXT("from_cm")),ReadVec(S,TEXT("to_cm")),PawnGround?ECC_Pawn:ECC_Visibility,Params);
        Result->SetStringField(TEXT("collision_channel"),PawnGround?TEXT("pawn"):TEXT("visibility"));
        Result->SetBoolField(TEXT("trace_complex"),!PawnGround);'''

def patched_observer(text):
    if MARKER in text:return text
    if text.count(OLD)!=1:raise ValueError('Ground observer source differs from reviewed ray implementation')
    return text.replace(OLD,NEW)

def can_upgrade(prior):
    # Preserve completed interaction measurements under their original observer.
    return not any(k!='pose_ground' and v.get('completed') for k,v in prior.get('episodes',{}).items())

def prepare_ground_observer(run,output):
    """Caller owns original evaluator engine and task locks; never move the slot."""
    r=read_json(run/'run.json');project=run/'workspace/project'
    if r.get('status') not in {'collected','measured'}:raise ValueError('Base collection must be complete before ground observer upgrade')
    if tree_digest(Path(r['source']))!=r['source_sha256']:raise ValueError('Frozen candidate changed')
    if tree_digest(project)!=r['verification_source_sha256']:raise ValueError('Verifier source changed')
    target=project/'Plugins/BenchRuntime/Source/BenchRuntime/Private/BenchObserver.cpp'
    original=target.read_text()
    if MARKER in original:return True
    prior=read_json(output/'run.json') if (output/'run.json').exists() else {}
    if not can_upgrade(prior):return False
    replacement=patched_observer(original)
    info=json.loads(subprocess.run(['docker','inspect',r['container']],capture_output=True,text=True,check=True,timeout=20).stdout)[0]
    if info['State']['Running']:raise ValueError('Ground observer upgrade requires stopped verifier container')
    archive=run/'ground-query-recovery'/str(time.time_ns());archive.mkdir(parents=True)
    shutil.copy2(run/'run.json',archive/'run.before.json');shutil.copy2(target,archive/'BenchObserver.before.cpp')
    write_json(archive/'scope.json',{'scope':'ray collision_channel=pawn selects simple Pawn trace; default visibility and all interaction dispatch unchanged','candidate_source_sha256':r['source_sha256'],'retained_episode_observer_sha256':r['observer_sha256']})
    try:
        target.write_text(replacement)
        subprocess.run(['docker','start',r['container']],check=True,capture_output=True,timeout=180)
        build_output='/workspace/build-ground-query-'+archive.name
        with (archive/'build.log').open('w') as log:
            subprocess.run(['docker','exec',r['container'],'python3','/opt/l3-public/ue.py','build','/workspace/project','--output',build_output,'--jobs','12','--blueprints'],stdout=log,stderr=log,check=True,timeout=3600)
    except Exception:
        target.write_text(original)
        write_json(archive/'result.json',{'status':'build_failed_original_observer_source_restored'})
        raise
    finally:
        subprocess.run(['docker','stop','--time','10',r['container']],capture_output=True,timeout=30)
    if tree_digest(Path(r['source']))!=r['source_sha256']:raise ValueError('Frozen candidate changed during ground observer build')
    if output.exists():shutil.move(output,archive/'runtime-output.before')
    sub=run/'workspace/runtime-geometry-v2'
    if sub.exists():shutil.move(sub,archive/'runtime-episodes.before')
    r['observer_sha256']=tree_digest(project/'Plugins/BenchRuntime')
    r['verification_source_sha256']=tree_digest(project)
    r['ground_query_observer_recovery']={'archive':str(archive),'scope':'Pawn collision for explicit ground queries only','retained_episode_observer_sha256':read_json(archive/'run.before.json')['observer_sha256']}
    write_json(run/'run.json',r)
    write_json(archive/'result.json',{'status':'built','observer_sha256':r['observer_sha256'],'verification_source_sha256':r['verification_source_sha256']})
    return True
