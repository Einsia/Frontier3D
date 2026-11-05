"""Bind visual review to a frozen equipped submission and independent renders."""
from pathlib import Path
from .protocol import read_json, digest, tree_digest, VIEWS


INTERIOR_YAWS = (0, 90, 180, 270)

def interior_images(evidence):
    return [evidence / "episodes/views" / f"building_{i:02}_interior{yaw}.png"
            for i in range(11) for yaw in INTERIOR_YAWS]

def review_context(run: Path, trial: Path | None = None):
    if trial is None:
        return run, {'tested_model': None, 'scope': 'integration fixture; no autonomous benchmark eligibility'}
    trial = trial.resolve()
    generation = read_json(trial / 'trial.json')
    verification = read_json(run / 'run.json')
    if generation.get('status') != 'generated_awaiting_independent_verification':
        raise ValueError('Visual review requires a frozen generated submission')
    if generation.get('submission_manifest_sha256') != digest(trial / 'submission-manifest.json'):
        raise ValueError('Submission manifest changed')
    source_hash = tree_digest(trial / 'workspace/project')
    if verification.get('kind') != 'submission_verification' or verification.get('source_sha256') != source_hash:
        raise ValueError('Independent renders belong to a different submission')
    if verification.get('status') not in {'measured', 'failed'}:
        raise ValueError('Wait for independent verification to finish')
    if not verification.get('episodes', {}).get('views', {}).get('completed'):
        raise ValueError('Independent multiview capture is incomplete')
    evidence = run / 'workspace'
    if tree_digest(evidence / 'project') != verification.get('verification_source_sha256'):
        raise ValueError('Verification source changed after freezing')
    images = [evidence / 'episodes/views' / (v + '.png') for v in VIEWS]
    images += interior_images(evidence)
    from PIL import Image
    for image in images:
        if image.is_symlink():
            raise ValueError('Symlinked review evidence is not accepted')
        with Image.open(image) as decoded:
            decoded.verify()
    equipment = read_json(trial / 'preflight-complete.json')['input_and_material_hashes']
    public_inputs=set(('PROMPT.md', 'input/reference.jpg')) | {k for k in equipment if k.startswith('input/')}
    for relative in sorted(public_inputs):
        if digest(trial / 'workspace' / relative) != equipment.get(relative):
            raise ValueError('Frozen public review input changed: ' + relative)
    return evidence, {'tested_model': generation['model'], 'trial': str(trial),
                     'source_sha256': source_hash,
                     'scope': 'equipped autonomous submission; independent rendered evidence',
                     'verification_status': verification['status'],
                     'verification_error': verification.get('error'),
                     'interior_capture_protocol': 'four_fixed_yaws_v2',
                     'frozen_image_hashes': {str(p.relative_to(run)): digest(p) for p in images}}
