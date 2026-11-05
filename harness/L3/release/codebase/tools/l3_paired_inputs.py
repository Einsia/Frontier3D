"""Reconstruct only hash-verified organizer inputs for a paired model trial."""
import hashlib
import json
import shutil
from pathlib import Path

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate(root):
    value=json.loads((root/'paired-inputs.json').read_text())
    for group,base in [('workspace',root/'workspace'),('public',root/'public')]:
        for name,expected in value[group].items():
            rel=Path(name)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Invalid paired input path')
            p=base/rel
            if p.is_symlink() or not p.is_file() or sha(p)!=expected:
                raise ValueError('Paired initial input differs: '+group+'/'+name)
    return value

def restore(root,baseline):
    original=json.loads((baseline/'preflight-complete.json').read_text())
    workspace=root/'workspace'
    # Public tools were mounted read-only for the authoring agent.
    for name,expected in original['public_tool_hashes'].items():
        src=baseline/'public'/name
        if src.is_symlink() or sha(src)!=expected:raise ValueError('Baseline public tool changed')
        dst=root/'public'/name
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    shutil.rmtree(workspace/'project/Plugins/BenchRuntime')
    shutil.copytree(root/'public/BenchRuntime',workspace/'project/Plugins/BenchRuntime')
    # Copy only initial asset bytes still matching the pre-generation manifest.
    # Changed candidate files are never copied; unchanged initial bytes are allowed.
    for name,expected in original['input_and_material_hashes'].items():
        dst=workspace/name
        if name.startswith('project/Content/') or name=='kenney-import.json':
            src=baseline/'workspace'/name
            if src.is_symlink() or sha(src)!=expected:
                raise ValueError('Baseline asset was modified; cannot use candidate bytes: '+name)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        if not dst.is_file() or sha(dst)!=expected:
            src=baseline/'workspace'/name
            if src.is_symlink() or not src.is_file() or sha(src)!=expected:
                raise ValueError('Initial input cannot be reconstructed without candidate changes: '+name)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    value={'baseline_trial':str(baseline),'baseline_preflight_sha256':sha(baseline/'preflight-complete.json'),
           'workspace':original['input_and_material_hashes'],'public':original['public_tool_hashes'],
           'policy':'Exact frozen initial files only; no candidate source, previews, logs, or session history'}
    (root/'paired-inputs.json').write_text(json.dumps(value,indent=2)+'\n')
    validate(root)
    return {'workspace_files':len(value['workspace']),'public_files':len(value['public'])}
