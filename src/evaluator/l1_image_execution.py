"""Visual v2 delivery bindings, explicitly without CAD equivalence claims."""
from pathlib import Path

from .l1_edit_validity import combine
from .l1_file_io import run_file_io
from .spec import EvalSpec

SCOPE = 'l1-image-delivery-binding-v2'


def bind_delivery(*, original_artifacts, seed_root, output_root, spec_path, deadline):
    spec = EvalSpec.load(spec_path)
    files = {}
    for name in ('scene.blend', 'scene.glb'):
        files[name] = {}
        for side, path in (('baseline', original_artifacts[name]), ('seed', Path(seed_root) / name)):
            row = run_file_io('hash', {'path': str(path)}, output=output_root / 'file_io', deadline=deadline)
            files[name][side] = {'path': str(path), 'sha256': row['sha256'], 'bytes': row['bytes']}
    return {'protocol': 'l1-reproduction-v1', 'status': 'ok', 'scope': SCOPE,
        'spec_sha256': spec.digest, 'files': files, 'geometry_equivalence': 'not_measured',
        'format_consistency': {'status': 'not_configured', 'reason': 'Outside visual v2 scoring scope'},
        'reason': 'Delivery bytes bound only; loadability, renders and material audits checked in every seed quality report'}


def measure_execution(spec, evidence):
    harness = evidence.get('harness', {})
    runs = harness.get('seed_runs', {})
    proofs = harness.get('reproduction_consistency', {}).get('per_seed', {})
    rows = {}
    for seed in map(str, spec.seeds):
        run, proof = runs.get(seed, {}), proofs.get(seed, {})
        hashes, files = run.get('artifact_sha256', {}), proof.get('files', {})
        bound = (proof.get('scope') == SCOPE and proof.get('status') == 'ok'
                 and proof.get('spec_sha256') == spec.digest
                 and proof.get('geometry_equivalence') == 'not_measured'
                 and all(hashes.get(n) and files.get(n, {}).get('seed', {}).get('sha256') == hashes[n]
                         for n in ('scene.blend', 'scene.glb')))
        status = 'failed' if run.get('passed') is False else 'passed' if run.get('passed') is True and bound else 'not_measurable'
        rows[seed] = {'status': status, 'execution_passed': run.get('passed'), 'delivery_bound': bool(bound)}
    status = combine(r['status'] for r in rows.values())
    return float(status == 'passed'), {'measurement_status': status, 'per_seed': rows,
        'semantic_reproduction_required': False, 'geometry_equivalence': 'not_measured',
        'scope': 'Execution and bound delivery only; independent rendering and integrity required by all_seed_checks'}
