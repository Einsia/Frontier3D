"""Verify frozen submission identity before independent collection."""
from pathlib import Path
import json
from harness.L3.MinecraftVillage.protocol import digest
def validate_submission(trial,key,model,effort=None):
    trial=Path(trial)
    generation=json.loads((trial/'trial.json').read_text())
    environment=json.loads((trial/'environment.json').read_text())
    manifest=json.loads((trial/'submission-manifest.json').read_text())
    if generation.get('status')!='generated_awaiting_independent_verification' or generation.get('model')!=model:
        raise ValueError('Submission model/status mismatch')
    if environment.get('task_key')!=key:raise ValueError('Submission task mismatch')
    if effort and generation.get('reasoning_effort')!=effort:raise ValueError('Submission effort mismatch')
    files=manifest.get('files',manifest)
    if 'files' in manifest and (manifest.get('model')!=model or manifest.get('effort')!=effort):
        raise ValueError('Frozen manifest identity mismatch')
    if not files:raise ValueError('Empty frozen manifest')
    root=(trial/'workspace/project').resolve()
    for rel,sha in files.items():
        path=(root/rel).resolve()
        if not path.is_relative_to(root) or not path.is_file() or digest(path)!=sha:
            raise ValueError('Frozen submission changed: '+rel)
    return files
