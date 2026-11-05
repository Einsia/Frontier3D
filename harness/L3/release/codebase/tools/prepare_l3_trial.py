"""Prepare an isolated UE authoring trial; no historical candidate is exposed."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import socket
import http.client
from urllib.parse import urlsplit, unquote


def codex_config(model, effort="high"):
    # The authorized provider rejects fallback requests containing web_search or
    # namespace tools even before a tool is called. Keep native function tools
    # and high reasoning; these trials receive their assets offline.
    extra = ('web_search="disabled"\n[features]\nmulti_agent=false\n'
             '[agents]\nmax_threads=1\n') if model in {"gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol", "qwen3.8-max"} else ""
    return ('model='+json.dumps(model)+'\nmodel_provider="l3"\n'
            'model_reasoning_effort='+json.dumps(effort)+'\n'+extra+
            '[model_providers.l3]\nname="L3 fixed model gateway"\n'
            'base_url="http://127.0.0.1:8765/v1"\nwire_api="responses"\n'
            'env_key="L3_MODEL_API_KEY"\n')


def docker_running_snapshot():
    """Read mounts in one list request, without inspecting unrelated containers."""
    endpoint=os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    if not endpoint:
        endpoint=json.loads(subprocess.check_output(
            ['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}'],
            text=True,timeout=10))
    parsed=urlsplit(endpoint)
    if parsed.scheme!='unix':return None
    class UnixConnection(http.client.HTTPConnection):
        def connect(self):
            self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(unquote(parsed.path))
    connection=UnixConnection('localhost',timeout=20)
    try:
        connection.request('GET','/containers/json?all=0')
        response=connection.getresponse()
        if response.status!=200:
            raise RuntimeError('Docker container list returned HTTP '+str(response.status))
        containers=json.loads(response.read())
        if not isinstance(containers,list) or any(
            not isinstance(c,dict) or not isinstance(c.get('Mounts'),list)
            or any(not isinstance(m,dict) or not isinstance(m.get('Source'),str) for m in c['Mounts'])
            for c in containers):
            raise RuntimeError('Docker container list lacks valid mount evidence')
        return containers
    except (OSError,ValueError,http.client.HTTPException) as exc:
        raise RuntimeError('Cannot obtain Docker engine mount snapshot: '+str(exc)) from exc
    finally:
        connection.close()


def assert_engine_available(engine):
    containers=docker_running_snapshot()
    if containers is not None:
        for info in containers:
            if any(Path(m['Source']).resolve()==engine for m in info['Mounts']):
                raise ValueError('Dedicated engine is in use by '+str(info.get('Names',info.get('Id','unknown'))))
        return
    # A slow Docker daemon must not leave a generation worker stuck forever.
    # Fail closed: inability to inspect is never evidence that an engine is free.
    deadline=time.monotonic()+60
    try:
        containers=subprocess.check_output(['docker','ps','-q'],text=True,timeout=20).split()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Docker engine availability check timed out while listing containers') from exc
    for cid in containers:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            raise RuntimeError('Docker engine availability check exceeded its 60-second budget')
        try:
            result=subprocess.run(['docker','inspect',cid],text=True,capture_output=True,timeout=min(20,remaining))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('Docker engine availability check timed out while inspecting '+cid) from exc
        if result.returncode:
            # Containers may disappear between listing and inspection.
            # Only this specific race is safe to ignore.
            if 'no such object: '+cid in result.stderr.lower() or 'no such container: '+cid in result.stderr.lower():
                continue
            raise RuntimeError('Cannot inspect Docker container: '+result.stderr.strip())
        info=json.loads(result.stdout)[0]
        # A container can stop after docker ps but before inspect.
        if info.get('State',{}).get('Running') is False:continue
        if any(Path(m['Source']).resolve()==engine for m in info['Mounts']):
            raise ValueError('Dedicated engine is in use by '+info.get('Name',cid))


def prepare(repo, output, engine, gpu, model="gpt-6-luna", task_path=None, effort="high", provider=None, gateway_script=None, native_cli=None, cpus=16):
    assets_root=Path(os.environ.get('L3_ASSET_ROOT',str(repo.parent/'l3-assets')))
    base_engine=(Path(os.environ.get('L3_UE_ROOT',str(repo.parent/'engines/UE_5.8.3_source/UnrealEngine-release')))).resolve()
    if engine==base_engine or not (engine/'Engine/Binaries/Linux/UnrealEditor-Cmd').is_file():
        raise ValueError('Supply a complete dedicated engine copy')
    if task_path is not None:
        task_path=task_path.resolve()
        sys.path.insert(0,str(repo))
        from tools.validate_l3_suite import validate_task
        validate_task(task_path)
        spec=json.loads((task_path/'task.json').read_text())
        if spec.get('execution_status')!='generation_ready':raise ValueError('Task package is not generation-ready')
    suite_models = task_path is not None and spec.get('package_format') != 'minecraft-openworld-v1'
    assert_engine_available(engine)
    output.mkdir(parents=True,exist_ok=True)
    workspace=output/'workspace';workspace.mkdir(exist_ok=False)
    for folder in ['input','.home','.codex','.cache/ue','project/Source/L3Environment','project/Config']:
        (workspace/folder).mkdir(parents=True,exist_ok=True)
    cache_seed=repo/'data/l3/preparation/l3-suite-20261023/equipment-smoke'
    seeded_cache=None
    if task_path is not None and cache_seed.resolve()!=output.resolve() and (cache_seed/'trial.json').is_file():
        seed_status=json.loads((cache_seed/'trial.json').read_text())
        seed_dir=cache_seed/'workspace/.cache/ue'
        if seed_status.get('equipment_status')=='ready' and seed_dir.is_dir():
            subprocess.run(['cp','-a','--reflink=auto',str(seed_dir)+'/.',str(workspace/'.cache/ue')],check=True)
            seeded_cache=str(seed_dir)
    public=output/'public';public.mkdir()
    shutil.copy2(Path(__file__).resolve().parents[5]/'configs/release/model-harness-contract.json',public/'model-harness-contract.json')
    for name in ['ue.py','ASSETS.md']:
        shutil.copy2(repo/'ue5/agent_environment'/name,public/name)
    for name in ['ue_import_l3_materials.py','ue_import_l3_kenney.py','l3_model_bridge.py','l3_usage.py','l3_api_control.py']:
        shutil.copy2(repo/'tools'/name,public/name)
    shutil.copytree(repo/'ue5/BenchRuntime',public/'BenchRuntime')
    task=task_path or repo/'tasks/L3/MinecraftVillage'
    from tools.l3_public_inputs import stage_public_inputs
    stage_public_inputs(task/'environment/input', workspace/'input')
    if not (workspace/'input/ASSETS.md').exists():shutil.copy2(public/'ASSETS.md',workspace/'input/ASSETS.md')
    if suite_models:
        for name in ['l3_assets.py','ue_import_l3_models.py']:shutil.copy2(repo/'tools'/name,public/name)
        shutil.copy2(workspace/'input/ASSETS.md',public/'ASSETS.md')
    project=workspace/'project'
    shutil.copytree(public/'BenchRuntime',project/'Plugins/BenchRuntime')
    descriptor={'FileVersion':3,'EngineAssociation':'5.8',
                'Modules':[{'Name':'L3Environment','Type':'Runtime','LoadingPhase':'Default'}],
                'Plugins':[{'Name':x,'Enabled':True} for x in ['BenchRuntime','PythonScriptPlugin','EditorScriptingUtilities']]}
    (project/'L3Environment.uproject').write_text(json.dumps(descriptor,indent=2))
    for suffix,kind in [('', 'Game'),('Editor','Editor')]:
        name='L3Environment'+suffix
        (project/'Source'/(name+'.Target.cs')).write_text('using UnrealBuildTool;\npublic class '+name+'Target: TargetRules { public '+name+'Target(TargetInfo Target):base(Target) { Type=TargetType.'+kind+'; DefaultBuildSettings=BuildSettingsVersion.V7; IncludeOrderVersion=EngineIncludeOrderVersion.Latest; ExtraModuleNames.Add("L3Environment"); } }\n')
    source=project/'Source/L3Environment'
    (source/'L3Environment.Build.cs').write_text('using UnrealBuildTool; public class L3Environment:ModuleRules { public L3Environment(ReadOnlyTargetRules Target):base(Target) { PCHUsage=PCHUsageMode.UseExplicitOrSharedPCHs; PublicDependencyModuleNames.AddRange(new string[]{"Core","CoreUObject","Engine","InputCore","BenchRuntime"}); } }\n')
    (source/'L3Environment.cpp').write_text('#include "Modules/ModuleManager.h"\nIMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl,L3Environment,"L3Environment");\n')
    (source/'L3Starter.h').write_text('#pragma once\n#include "CoreMinimal.h"\n#include "GameFramework/GameModeBase.h"\n#include "L3Starter.generated.h"\nUCLASS() class AL3Starter : public AGameModeBase { GENERATED_BODY() public: virtual void BeginPlay() override; };\n')
    (source/'L3DefaultEnvironment.h').write_text('#pragma once\n#include "Engine/World.h"\n#include "Engine/DirectionalLight.h"\n#include "Components/DirectionalLightComponent.h"\n#include "Components/LightComponent.h"\n#include "Engine/SkyLight.h"\n#include "Engine/TextureCube.h"\n#include "Components/SkyLightComponent.h"\n#include "Engine/StaticMeshActor.h"\n#include "Engine/StaticMesh.h"\n#include "Components/StaticMeshComponent.h"\n#include "Materials/MaterialInterface.h"\n// Generic daylight only; no task geometry or interaction implementation.\ninline void L3AddDefaultDaylight(UWorld* World) {\n auto Light=World->SpawnActor<ADirectionalLight>();\n Light->GetRootComponent()->SetMobility(EComponentMobility::Movable);\n Light->SetActorRotation(FRotator(-45,-30,0));Light->GetLightComponent()->SetIntensity(3.f);\n auto Sky=World->SpawnActor<ASkyLight>();\n auto SC=Sky->GetLightComponent();SC->SetMobility(EComponentMobility::Movable);\n SC->SourceType=SLS_SpecifiedCubemap;\n SC->SetCubemap(LoadObject<UTextureCube>(nullptr,TEXT("/Engine/MapTemplates/Sky/DaylightAmbientCubemap.DaylightAmbientCubemap")));\n SC->SetIntensity(1.0f);SC->SetLowerHemisphereColor(FLinearColor(0.08f,0.08f,0.08f));\n auto Dome=World->SpawnActor<AStaticMeshActor>();\n auto DC=Dome->GetStaticMeshComponent();DC->SetMobility(EComponentMobility::Movable);\n DC->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Sphere.Sphere")));\n DC->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/L3Environment/M_DefaultSky.M_DefaultSky")));\n Dome->SetActorEnableCollision(false);\n DC->SetCollisionProfileName(TEXT("NoCollision"));\n DC->SetCollisionResponseToAllChannels(ECR_Ignore);\n DC->SetWorldScale3D(FVector(5000));DC->SetCollisionEnabled(ECollisionEnabled::NoCollision);DC->SetCastShadow(false);\n}\n')
    (source/'L3Starter.cpp').write_text('''#include "L3Starter.h"
#include "L3DefaultEnvironment.h"
#include "Engine/World.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "Engine/DirectionalLight.h"
#include "Components/StaticMeshComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Materials/MaterialInterface.h"
#include "Engine/SkyLight.h"
#include "Engine/TextureCube.h"
#include "Components/SkyLightComponent.h"
#include "Components/LightComponent.h"
void AL3Starter::BeginPlay() {
 Super::BeginPlay();
 L3AddDefaultDaylight(GetWorld());
 auto TestBox=[&](FVector P,FVector Size) {
  auto A=GetWorld()->SpawnActor<AStaticMeshActor>(P,FRotator::ZeroRotator);
  auto C=A->GetStaticMeshComponent();C->SetMobility(EComponentMobility::Movable);
  C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube")));
  C->SetWorldScale3D(Size/100.f);
  C->SetMaterial(0,LoadObject<UMaterialInterface>(nullptr,TEXT("/Game/L3Materials/Kenney/M_brick_grey.M_brick_grey")));
 };
 TestBox(FVector(160,80,-20),FVector(1200,1000,40));
 TestBox(FVector(160,700,0),FVector(600,500,40));
 TestBox(FVector(160,950,150),FVector(600,20,300));
 TestBox(FVector(-140,700,150),FVector(20,500,300));
 TestBox(FVector(460,700,150),FVector(20,500,300));
 TestBox(FVector(160,700,310),FVector(600,500,20));
 TestBox(FVector(160,800,60),FVector(80,80,100));
 const TCHAR* Names[]={TEXT("grass_top"),TEXT("wood"),TEXT("brick_grey"),TEXT("oven"),TEXT("wheat_stage4"),TEXT("water")};
 for(int32 I=0;I<6;++I) {
  auto A=GetWorld()->SpawnActor<AStaticMeshActor>(FVector((I%3)*160,(I/3)*160,50),FRotator::ZeroRotator);
  auto C=A->GetStaticMeshComponent();C->SetMobility(EComponentMobility::Movable);
  C->SetStaticMesh(LoadObject<UStaticMesh>(nullptr,TEXT("/Engine/BasicShapes/Cube.Cube")));
  const FString P=FString::Printf(TEXT("/Game/L3Materials/Kenney/M_%s.M_%s"),Names[I],Names[I]);
  if(auto M=LoadObject<UMaterialInterface>(nullptr,*P))C->SetMaterial(0,M);
 }
}
''')
    (project/'Config/DefaultEngine.ini').write_text('''[/Script/EngineSettings.GameMapsSettings]
GameDefaultMap=/Engine/Maps/Entry
GlobalDefaultGameMode=/Script/L3Environment.L3Starter
[/Script/Engine.RendererSettings]
r.DefaultFeature.AutoExposure=False
r.DefaultFeature.MotionBlur=False
r.DynamicGlobalIlluminationMethod=0
r.ReflectionMethod=0
[/Script/LinuxTargetPlatform.LinuxTargetSettings]
+TargetedRHIs=SF_VULKAN_SM5
''')
    prompt=(task/'instruction.md').read_text()+'''

## Workspace
Work in /workspace/project. The compiled starter is a generic lighting and material test fixture, not part of the village. Replace its test geometry. L3DefaultEnvironment.h provides L3AddDefaultDaylight(World), a reusable sky and lighting setup; you may call it or supply your own environment. UE5_ROOT points to the installed engine. Read input/ASSETS.md, input/REQUIREMENTS.md and input/INTEGRATION.md. Kenney materials are imported under /Game/L3Materials/Kenney; exact paths are in kenney-import.json. Poly Haven materials are available at /assets/polyhaven. The library is optional; you may adapt or create materials. Kenney materials expose a scalar UVScale parameter, default 1, for your own material instances.

Build: python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16
Add --blueprints when changing Blueprint assets. The default checks C++ without repeatedly compiling engine Blueprint content. Independent final validation is separate.
Preview: python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z
Use a fresh output directory for each invocation. View the supplied reference and your rendered PNGs with image tools. Iterate independently within 3600 seconds, including all model calls, edits, builds and previews. The clock starts after equipment and connection checks. Finish with the project, bindings.json, assets_used.json, README and genuine final previews. Network access is disabled except for the model service.
'''
    if task_path is not None:prompt=(task/'PROMPT.md').read_text()
    (workspace/'PROMPT.md').write_text(prompt)
    (workspace/'.codex/config.toml').write_text(codex_config(model, effort))
    (workspace/'.codex/config.toml').chmod(0o600)
    # Unix socket paths have a short kernel limit; all logs and artifacts stay in output.
    gateway=Path(tempfile.mkdtemp(prefix='l3-model-gateway-'))
    (output/'model-stage.txt').write_text('preflight')
    hostlog=(output/'gateway.log').open('w')
    provider=provider or repo.parent/'.config/3dbench/provider.json'
    server=subprocess.Popen(['python3',str(gateway_script or repo/'tools/l3_model_bridge.py'),'serve','--socket',str(gateway/'api.sock'),'--provider',str(provider),'--ledger',str(output/'model-requests.jsonl'),'--stage-file',str(output/'model-stage.txt')],stdout=hostlog,stderr=hostlog,start_new_session=True,env={**os.environ,'L3_EXPECTED_MODEL':model,'L3_EXPECTED_EFFORT':effort})
    base_engine=Path(os.environ.get('L3_UE_ROOT',str(repo.parent/'engines/UE_5.8.3_source/UnrealEngine-release')))
    image=os.environ.get('L3_UE_IMAGE','3dbench-l3-agent:ue5.8.3-codex0.163.0')
    name='l3-'+output.name.lower().replace('_','-')+'-'+__import__('hashlib').sha256(str(output).encode()).hexdigest()[:10]
    command=['docker','run','-d','--name',name,'--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--cpus',str(cpus),'--memory','64g','--pids-limit','4096','--shm-size','2g','--gpus','device='+str(gpu),
             '--user',f'{os.getuid()}:{os.getgid()}','-w','/workspace']
    for key,value in {'HOME':'/workspace/.home','CODEX_HOME':'/workspace/.codex','L3_MODEL_API_KEY':'local-bridge-no-secret',
                      'UE5_ROOT':str(base_engine),'UE_LocalDataCachePath':'/workspace/.cache/ue','NVIDIA_DRIVER_CAPABILITIES':'graphics,utility,compute'}.items():
        command+=['-e',key+'='+value]
    for host,container,ro in [(workspace,'/workspace',False),(public,'/opt/l3-public',True),(engine,str(base_engine),False),
                              (gateway,'/model-gateway',True),
                              (assets_root/'polyhaven-2k-2026-10-16','/assets/polyhaven',True),
                              (assets_root/'kenney-voxel-1.0-tiles','/assets/kenney',True)]:
        command+=['--mount',f'type=bind,src={host},dst={container}'+(',readonly' if ro else '')]
    if suite_models:
        command+=['--mount',f'type=bind,src={assets_root}/kenney-suite-20261023,dst=/assets/models,readonly']
    if native_cli:
        command+=['--mount',f'type=bind,src={native_cli},dst=/opt/cli/node_modules,readonly']
        shutil.copy2(repo/'tools/l3_native_agent.py',public/'l3_native_agent.py')
    command+=[image]
    record={'kind':'equipped_agent_trial','container':name,'container_id':None,'docker_command':command,'gateway_pid':server.pid,
            'gateway_directory':str(gateway),'workspace':str(workspace),'engine_copy':str(engine),'budget_seconds':3600,
            'network':'none; host Unix gateway permits only Responses and models endpoints','model':model,'reasoning_effort':effort,'status':'container_starting','seeded_shader_cache':seeded_cache}
    if task_path is not None:
        refs=json.loads((workspace/'input/references.json').read_text())
        record.update(task_key=spec['key'],task_path=str(task),input_mode=spec['input_mode'],
            reference_images=['/workspace/input/'+x['path'] for x in refs['images']],
            budget_seconds=None,target_seconds=3600,completion_policy='complete_delivery',
            task_manifest_sha256=__import__('hashlib').sha256((task/'package-manifest.json').read_bytes()).hexdigest())
    (output/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    cid=subprocess.check_output(command,text=True,timeout=180).strip()
    subprocess.run(['docker','exec','-d',name,'python3','/opt/l3-public/l3_model_bridge.py','bridge','--socket','/model-gateway/api.sock'],check=True,timeout=30)
    record.update(container_id=cid,status='preflight_pending')
    (output/'environment.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'container':name,'status':record['status']}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--engine',type=Path,required=True);p.add_argument('--gpu',type=int,required=True)
    p.add_argument('--model',default='gpt-6-luna')
    p.add_argument('--task',type=Path)
    a=p.parse_args();prepare(Path(__file__).resolve().parents[1],a.output.resolve(),a.engine.resolve(),a.gpu,a.model,a.task)
