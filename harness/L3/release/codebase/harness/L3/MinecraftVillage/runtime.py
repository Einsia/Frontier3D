"""UE compile/render runner. Engine absence is infrastructure status, never 0 quality."""
from __future__ import annotations
import argparse, os, shutil, signal, subprocess, time
from pathlib import Path
from .protocol import *
ROOT=Path(__file__).resolve().parents[3]


def doctor(engine: Path | None):
    result={'status':'needs_engine','engine':str(engine) if engine else None,
            'epic_download':'https://www.unrealengine.com/en-US/linux','required_version':'5.8',
            'bwrap':shutil.which('bwrap'),'graphics':'requires an actual Vulkan render test'}
    if engine:
        version=engine/'Engine/Build/Build.version'
        editor=engine/'Engine/Binaries/Linux/UnrealEditor'
        if version.is_file() and editor.is_file():
            v=read_json(version);result['version']=v
            result['executable']=os.access(editor,os.X_OK)
            result['status']='engine_present_unverified' if (v.get('MajorVersion'),v.get('MinorVersion'))==(5,8) else 'wrong_engine_version'
    if result['status']=='engine_present_unverified' and not result['executable']:result['status']='engine_not_executable'
    return result


def process(command, cwd, log, timeout, env=None):
    with log.open('w') as output:
        p=subprocess.Popen(command,cwd=cwd,stdout=output,stderr=subprocess.STDOUT,
                           start_new_session=True,env=env or os.environ.copy())
        try: return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid,signal.SIGTERM)
            try: p.wait(timeout=5)
            except subprocess.TimeoutExpired: os.killpg(p.pid,signal.SIGKILL);p.wait()
            return 124


def isolated(command, engine, project, output, deps=None, nvidia_device=None, engine_copy=None, building=False):
    """Private network/pid/home/tmp, immutable source, explicit generated outputs."""
    if not shutil.which('bwrap'): raise RuntimeError('bwrap is required to execute generated native code')
    args=['bwrap','--die-with-parent','--unshare-all','--new-session','--clearenv']
    for path in ['/usr','/bin','/sbin','/lib','/lib64','/etc','/sys']:
        if Path(path).exists(): args += ['--ro-bind',path,path]
    if nvidia_device is None:
        args += ['--dev-bind','/dev','/dev']
    else:
        if type(nvidia_device) is not int or nvidia_device<0: raise ValueError('invalid NVIDIA device index')
        selected=Path(f'/dev/nvidia{nvidia_device}')
        if not selected.exists(): raise ValueError('NVIDIA device does not exist: '+str(selected))
        args += ['--dev','/dev']
        for node in ['/dev/nvidiactl','/dev/nvidia-uvm','/dev/nvidia-uvm-tools','/dev/nvidia-modeset',str(selected)]:
            if Path(node).exists(): args += ['--dev-bind',node,node]
    args += ['--proc','/proc','--tmpfs','/tmp','--dir','/tmp/home',
             '--setenv','HOME','/tmp/home','--setenv','PATH','/usr/bin:/bin',
             '--setenv','LANG','C.UTF-8','--setenv','XDG_RUNTIME_DIR','/tmp',
             '--setenv','UE_LocalDataCachePath',str(output/'derived-data-cache'),
             '--bind' if building and engine_copy else '--ro-bind',str(engine_copy or engine),str(engine),
             '--bind',str(output),str(output),
             '--ro-bind',str(project),str(project),'--chdir',str(project)]
    # Source and configuration are immutable, including during commandlets.
    # Mount generated directories after the read-only project mount.
    build_roots=[project]+[p.parent for p in (project/'Plugins').rglob('*.uplugin')]
    for root in build_roots:
        for name in ('Binaries','Intermediate','Saved','DerivedDataCache'):
            writable=root/name;writable.mkdir(parents=True,exist_ok=True)
            args += ['--bind',str(writable),str(writable)]
    # Source builds write UBT logs and editor state inside the engine tree.
    # Redirect only these scratch directories; engine source/binaries stay read-only.
    for relative in ['Engine/Programs/UnrealBuildTool','Engine/Saved']:
        scratch=output/'engine-scratch'/relative;scratch.mkdir(parents=True,exist_ok=True)
        args += ['--bind',str(scratch),str(engine/relative)]
    if deps:
        args += ['--ro-bind',str(deps),str(deps),'--setenv','LD_LIBRARY_PATH',str(deps/'usr/lib/x86_64-linux-gnu')]
    return args+['--']+command


def run(project: Path, engine: Path | None, output: Path, deps: Path | None=None, e2e: Path | None=None, timeout=300,
        graphics_adapter: int | None=None, build_jobs: int=16, nvidia_device: int | None=None,
        engine_copy: Path | None=None, cache_from_run: Path | None=None):
    if graphics_adapter is not None and (type(graphics_adapter) is not int or graphics_adapter<0):
        raise ValueError('graphics_adapter must be a nonnegative Vulkan device index')
    if type(build_jobs) is not int or build_jobs<1: raise ValueError('build_jobs must be positive')
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:
        raise ValueError('episode timeout must be finite and positive')
    if nvidia_device is not None:
        if type(nvidia_device) is not int or nvidia_device<0: raise ValueError('invalid NVIDIA device index')
        if graphics_adapter not in (None,0): raise ValueError('Only Vulkan adapter 0 is visible with a selected NVIDIA device')
        graphics_adapter=0
    project=project.resolve();output=output.resolve();engine=engine.resolve() if engine else None
    if engine_copy:
        engine_copy=engine_copy.resolve()
        if engine_copy==engine or not engine or not (engine_copy/'Engine/Build/Build.version').is_file():
            raise ValueError('Source-build copy must be a separate, prepared engine tree')
        if digest(engine_copy/'Engine/Build/Build.version')!=digest(engine/'Engine/Build/Build.version'):
            raise ValueError('Engine copy version differs from base engine')
    output.mkdir(parents=True,exist_ok=False)
    env=doctor(engine);write_json(output/'environment.json',env)
    record={'schema_version':1,'status':env['status'],'project':str(project),'score':None,
            'graphics_adapter':graphics_adapter,'nvidia_device':nvidia_device,
            'build_jobs':build_jobs,'episode_timeout_seconds':timeout,
            'source_build_copy':str(engine_copy) if engine_copy else None,
            'engine_copy_scope':'dedicated to this submission; never share across candidates' if engine_copy else None}
    if env['status']!='engine_present_unverified':
        record['reason']='Install an authorized UE5 5.8 Linux build (archive or source), then rerun in a fresh output directory.'
        write_json(output/'run.json',record);return record
    # Keep the model's raw submission immutable; build a disposable copy.
    raw_project=project
    if cache_from_run:
        previous=read_json(cache_from_run/'run.json')
        if previous.get('submission_sha256')!=tree_digest(raw_project):
            raise ValueError('Cache seed must belong to the exact same submission')
        if read_json(cache_from_run/'environment.json').get('version')!=env.get('version'):
            raise ValueError('Cache seed engine version differs')
        cache=cache_from_run/'derived-data-cache'
        if cache.is_symlink() or any(p.is_symlink() for p in cache.rglob('*')):
            raise ValueError('Cache seed must not contain symlinks')
        shutil.copytree(cache,output/'derived-data-cache',symlinks=False)
        record['cache_seed_run']=str(cache_from_run.resolve())
    record['submission']=str(raw_project)
    record['submission_sha256']=tree_digest(raw_project)
    project=output/'project'
    shutil.copytree(raw_project,project,ignore=shutil.ignore_patterns('Binaries','Intermediate','Saved','DerivedDataCache'))
    record['project']=str(project)
    # Reuse the L1/L2 framework's project validator and UE compile command.
    from src.ue5.runtime import validate_project, UE5Config, build_smoke_command
    metadata=validate_project(project);descriptor=Path(metadata['project_file'])
    if not str(metadata['engine_association']).startswith('5.8'): raise ValueError('project must target 5.8')
    bindings=validate_bindings(read_json(project/'bindings.json'))
    tree_digest(project)  # rejects symlinks before copying observer
    plugin=project/'Plugins/BenchRuntime'
    if plugin.exists(): shutil.rmtree(plugin)
    shutil.copytree(ROOT/'ue5/BenchRuntime',plugin)
    desc=read_json(descriptor);plugins=[p for p in desc.get('Plugins',[]) if p['Name']!='BenchRuntime']
    desc['Plugins']=plugins+[{'Name':'BenchRuntime','Enabled':True}];write_json(descriptor,desc)
    source_hash=tree_digest(project)
    record.update(status='compiling',source_sha256=source_hash,observer_sha256=tree_digest(plugin),
                  task_sha256=tree_digest(ROOT/'tasks/L3/MinecraftVillage'))
    write_json(output/'run.json',record);write_json(output/'bindings.json',bindings)
    cfg=UE5Config(root=engine,editor=engine/'Engine/Binaries/Linux/UnrealEditor',runuat=engine/'Engine/Build/BatchFiles/RunUAT.sh')
    compilecmd=build_smoke_command(cfg,descriptor,output/'build',max_parallel_actions=build_jobs,disable_uba=True)
    # Build scripts are generated code too, so use the same isolation policy.
    code=process(isolated(compilecmd,engine,project,output,deps,nvidia_device,engine_copy,building=True),project,output/'build.log',1800)
    if code:
        record.update(status='build_failed',return_code=code);write_json(output/'run.json',record);return record
    plans=make_plans(bindings)
    if e2e:
        p=validate_plan(read_json(e2e))
        if p['kind']!='e2e': raise ValueError('workflow must be an evaluator-curated E2E plan')
        plans['e2e']=p
    for name,plan in plans.items():
        record.update(status='running',episode=name);write_json(output/'run.json',record)
        planpath=output/'plans'/(name+'.json');write_json(planpath,plan)
        evidence=output/'episodes'/name;evidence.mkdir(parents=True)
        command=[str(cfg.editor),str(descriptor),'-game','-unattended','-nosplash','-nosound','-nop4',
                 '-RenderOffscreen','-vulkan','-ResX=1280','-ResY=720','-Windowed','-ForceRes','-UseFixedTimeStep','-FPS=60',
                 '-DDC=NoZenLocalFallback',f'-corelimit={build_jobs}','-stdout','-FullStdOutLogOutput',f'-BenchPlan={planpath}',f'-BenchOutput={evidence}']
        if graphics_adapter is not None: command.append(f'-graphicsadapter={graphics_adapter}')
        code=process(isolated(command,engine,project,output,deps,nvidia_device,engine_copy),project,evidence/'engine.log',timeout)
        if code or not (evidence/'completed.json').is_file():
            record.update(status='runtime_failed',episode=name,return_code=code)
            write_json(output/'run.json',record);return record
        missing=[s['name'] for s in plan['steps'] if s['op']=='capture' and not (evidence/(s['name']+'.png')).is_file()]
        if missing:
            record.update(status='render_failed',episode=name,missing_captures=missing)
            write_json(output/'run.json',record);return record
    if source_hash!=tree_digest(project):
        record.update(status='source_integrity_failed',reason='Candidate source changed during execution')
        write_json(output/'run.json',record);return record
    record.update(status='executed',e2e_included=bool(e2e),evidence_sha256={
        str(p.relative_to(output)):digest(p) for p in sorted(output.rglob('*'))
        if p.is_file() and (p.relative_to(output).parts[0] in {'plans','episodes'} or p.name in {'environment.json','bindings.json','build.log'})})
    write_json(output/'run.json',record)
    return record


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('doctor');d.add_argument('--engine',type=Path)
    r=sub.add_parser('run');r.add_argument('--project',type=Path,required=True);r.add_argument('--engine',type=Path)
    r.add_argument('--output',type=Path,required=True);r.add_argument('--deps',type=Path);r.add_argument('--e2e',type=Path)
    r.add_argument('--graphics-adapter',type=int);r.add_argument('--build-jobs',type=int,default=16)
    r.add_argument('--nvidia-device',type=int,help='Expose only /dev/nvidiaN; Vulkan adapter becomes 0')
    r.add_argument('--engine-copy',type=Path,help='Independent source-build copy dedicated to this candidate; base engine stays read-only')
    r.add_argument('--cache-from-run',type=Path,help='Reuse derived cache only from the same submission and engine version')
    r.add_argument('--episode-timeout',type=float,default=300)
    e=sub.add_parser('evaluate');e.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    if a.cmd=='doctor': result=doctor(a.engine)
    elif a.cmd=='run': result=run(a.project,a.engine,a.output,a.deps,a.e2e,a.episode_timeout,a.graphics_adapter,a.build_jobs,a.nvidia_device,a.engine_copy,a.cache_from_run)
    else:
        from .evaluate import summarize
        result=summarize(a.run);write_json(a.run/'report.json',result)
    if 'evidence_sha256' in result:
        result={k:v for k,v in result.items() if k!='evidence_sha256'} | {'evidence_manifest':str(a.output/'run.json')}
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
