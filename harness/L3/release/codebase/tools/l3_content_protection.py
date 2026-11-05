"""Frozen content inputs with auditable isolated runtime materialization."""
from pathlib import Path, PurePosixPath
import json,hashlib,shutil,time

def files(root):
    result={}
    for p in sorted(Path(root).rglob('*')):
        if p.is_symlink():raise ValueError('Runtime content symlink forbidden')
        if p.is_file():result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result

def configured(output, project, source_sha256):
    marker=Path(output).parent/'source-write-protection.json'
    if not marker.exists():return None,[]
    config=json.loads(marker.read_text())
    if config.get('source_sha256')!=source_sha256:
        raise ValueError('Content protection source identity mismatch')
    paths=config.get('directories')
    if not isinstance(paths,list) or not paths:raise ValueError('Empty content protection')
    if config.get('mode','readonly') not in {'readonly','runtime_copy'}:raise ValueError('Unknown content protection mode')
    result=[]
    for value in paths:
        if not isinstance(value,str):raise ValueError('Invalid content directory')
        rel=PurePosixPath(value)
        if rel.is_absolute() or '..' in rel.parts or len(rel.parts)<2 or rel.parts[0]!='Content' or rel.parts[1]=='L3Verifier':
            raise ValueError('Content protection outside candidate content')
        host=Path(project)/rel
        if not host.is_dir() or not host.resolve().is_relative_to(Path(project).resolve()) or any(p.is_symlink() for p in [host,*host.parents]):
            raise ValueError('Unsafe content protection directory')
        result.append((value,host))
    return config,result

def content_mounts(output, project, source_sha256):
    config,paths=configured(output,project,source_sha256)
    if config is None:return []
    result=[];root=Path(output)/'runtime-content'
    for value,base in paths:
        host=base;readonly=True
        if config.get('mode')=='runtime_copy':
            root.mkdir(exist_ok=True)
            identity=hashlib.sha256(value.encode()).hexdigest()[:16]
            host=root/identity;seed=root/(identity+'-seed.json')
            base_files=files(base)
            expected={'source_sha256':source_sha256,'directory':value,'input_files':base_files}
            if seed.exists():
                if json.loads(seed.read_text())!=expected:raise ValueError('Frozen content seed changed')
                if not host.is_dir() or host.is_symlink():raise ValueError('Runtime content copy missing/unsafe')
            else:
                if host.exists():raise ValueError('Untracked runtime content copy exists')
                shutil.copytree(base,host)
                if files(host)!=base_files:raise ValueError('Runtime content seed copy mismatch')
                seed.write_text(json.dumps(expected,indent=2))
            readonly=False
        result.extend(['--mount',f'type=bind,src={host},dst=/workspace/project/{value}'+(',readonly' if readonly else '')])
    return result

def audit_content(output,project,source_sha256,phase):
    config,paths=configured(output,project,source_sha256)
    if config is None or config.get('mode')!='runtime_copy':return None
    records=[]
    for value,base in paths:
        identity=hashlib.sha256(value.encode()).hexdigest()[:16]
        root=Path(output)/'runtime-content';seed=json.loads((root/(identity+'-seed.json')).read_text())
        initial=files(base)
        if seed!={'source_sha256':source_sha256,'directory':value,'input_files':initial}:raise ValueError('Frozen content seed changed')
        current=files(root/identity)
        records.append({'directory':value,'input_files':initial,'runtime_files':current,
                        'changed_runtime_files':[k for k in sorted(set(initial)|set(current)) if initial.get(k)!=current.get(k)]})
    record={'protocol':'frozen_input_runtime_copy_v1','source_sha256':source_sha256,'phase':phase,
            'time':time.time(),'frozen_inputs_unchanged':True,'directories':records}
    folder=Path(output)/'runtime-content-audits';folder.mkdir(exist_ok=True)
    p=folder/(str(time.time_ns())+'.json');p.write_text(json.dumps(record,indent=2))
    return {'audit':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'protocol':record['protocol']}

def verify_audit(output,project,source_sha256,reference):
    p=Path(reference['audit'])
    if not p.resolve().is_relative_to((Path(output)/'runtime-content-audits').resolve()):raise ValueError('Content audit outside verifier')
    if hashlib.sha256(p.read_bytes()).hexdigest()!=reference['sha256']:raise ValueError('Content audit changed')
    record=json.loads(p.read_text())
    if record['source_sha256']!=source_sha256:raise ValueError('Content audit source mismatch')
    for row in record['directories']:
        identity=hashlib.sha256(row['directory'].encode()).hexdigest()[:16]
        if files(Path(project)/row['directory'])!=row['input_files']:raise ValueError('Frozen content changed')
        if files(Path(output)/'runtime-content'/identity)!=row['runtime_files']:raise ValueError('Runtime content changed after measurement')
    return record
