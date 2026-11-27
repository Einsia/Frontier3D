"""Read the complete native L2 audit population from bound execution records."""
from pathlib import Path

from src.agent_judge.protocol import read_json
from tools.evaluate_linear_candidate import pin


def native_audits(run, *, task=None):
    run = Path(run)
    manifest = read_json(run / 'run.json')
    record = read_json(run / 'execution_record.json')
    if any(not manifest.get(k) or manifest[k] != record.get(k) for k in ('task_id', 'spec_sha256')):
        raise ValueError('Native L2 execution identity differs')
    spec_path = run / 'configuration/eval_spec.json'
    pin(spec_path, record['evidence_sha256']['configuration/eval_spec.json'])
    seeds = read_json(spec_path)['seeds']
    if (not seeds or any(type(s) is not int for s in seeds)
            or len(set(seeds)) != len(seeds) or manifest.get('seeds') != seeds):
        raise ValueError('Native L2 seed population differs from bound configuration')
    if task is not None:
        spec_path = Path(task) / 'harness/eval_spec.json'
        pin(spec_path, record['task_files_sha256']['harness/eval_spec.json'])
        if read_json(spec_path)['seeds'] != seeds:
            raise ValueError('Native L2 seeds differ from the task contract')
    audits = {}
    for label in ['baseline', *(f'seed-{seed}' for seed in seeds)]:
        name = f'audit/{label}.json'
        path = run / name
        pin(path, record['evidence_sha256'][name])
        audits[label] = read_json(path)
    return manifest, record, audits
