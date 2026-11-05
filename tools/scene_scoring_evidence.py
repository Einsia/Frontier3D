"""Select retained, scene-bound rerenders as scoring evidence without editing submissions."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

from pathlib import Path

from tools.bench_control import load, atomic

from tools.evaluate_linear_candidate import pin

from tools.bench_repair_timer import mkdir

from src.evaluator.content_evidence_policy import VERSION, rerender_available

def checked(pointer):
    return pin(pointer['path'], pointer['sha256'])

def replay_images(scene, replay, bound_files):
    """Every scoring pixel must have existed in a hash-bound render receipt."""
    if not rerender_available(replay):
        raise ValueError('Successful native rerender evidence required')
    allowed = {str(Path(p['path']).resolve()):p for p in bound_files}
    result = {'scene.blend':checked(scene)}
    for name in ('main.png', 'alternate.png'):
        path = str(Path(replay['views'][name]['render_path']).resolve())
        if path not in allowed:
            raise ValueError('Rerender image was not bound to execution receipt')
        result[name] = checked(allowed[path])
    return result

def addition_images(source, manifest, *, level, folder=None):
    source = Path(source)
    folder = Path(folder or source/'scene_scoring_evidence')
    results = {};receipts = {}
    for seed in ('primary','seed-0','seed-1','seed-2'):
        current = manifest['variants'][seed]
        if level == 2:
            path = source/'legacy_image_integrity'/seed/'receipt.json'
            receipt = load(path)
            if receipt['source_bindings']['artifacts']['scene.blend'] != current['scene.blend']:
                raise ValueError('Image replay belongs to another scene')
            results[seed] = replay_images(current['scene.blend'],receipt['result'],receipt['evidence_files'])
            receipts[seed] = pin(path)
        else:
            integrity = load(source/'legacy_integrity/render_consistency.json')
            pointer = integrity['render_receipts'][seed];checked(pointer)
            receipt = load(pointer['path'])
            if receipt['scene'] != current['scene.blend'] or not receipt['source_unchanged']:
                raise ValueError('L1 saved render belongs to another scene')
            from tools.run_l1_strict_review import collect_native
            native = collect_native(Path(current['scene.blend']['path']), source/'legacy_detail/native'/seed,
                                    1, studio=False,main_required=True)
            results[seed] = {'scene.blend':checked(current['scene.blend']),
                'main.png':checked(receipt['view']['image']),
                'alternate.png':checked(native['renders']['alternate'])}
            receipts[seed] = pointer
    record = dict(policy=VERSION, source_variants=pin(source/'legacy_execution/variants.json'),
        variants=results, render_receipts=receipts,
        settings='Saved camera, frame, lights, materials, colour management and sampling; no scene edits or quality optimization',
        candidate_code_executed=False)
    mkdir(folder);atomic(folder/'images.json',record)
    return record

def native_images(run, *, folder=None):
    run=Path(run);record=load(run/'execution_record.json');manifest=load(run/'run.json')
    images={};audits={}
    for label in ('baseline','seed-0','seed-1','seed-2'):
        path=run/'audit'/(label+'.json')
        pin(path,record['evidence_sha256']['audit/'+label+'.json'])
        audit=load(path)
        if label=='baseline':scene=pin(run/'submission/scene.blend',record['artifact_sha256']['scene.blend'])
        else:
            attempt=manifest['attempts'][label][-1]
            scene=pin(Path(attempt['workspace'])/'output/scene.blend',attempt['artifact_sha256']['scene.blend'])
        files=[{'path':str(run/name),'sha256':digest} for name,digest in record['evidence_sha256'].items()]
        images['primary' if label=='baseline' else label]=replay_images(scene,audit['rerender'],files)
        audits[label]=pin(path)
    result=dict(policy=VERSION,source_execution_record=pin(run/'execution_record.json'),
        variants=images,audits=audits,candidate_code_executed=False)
    if folder:
        mkdir(Path(folder));atomic(Path(folder)/'images.json',result)
    return result

def scoring_manifest(source):
    path=Path(source)/'scene_scoring_evidence/images.json'
    if not path.exists():return None
    record=load(path)
    if record['policy']!=VERSION or record['source_variants']!=pin(Path(source)/'legacy_execution/variants.json'):
        raise ValueError('Rerender scoring policy/execution binding differs')
    original=load(Path(source)/'legacy_execution/variants.json')
    if set(record['variants'])!=set(original['variants']):raise ValueError('Scoring rerender seed population differs')
    for seed,images in record['variants'].items():
        if images['scene.blend']!=original['variants'][seed]['scene.blend']:
            raise ValueError('Scoring rerender scene differs from generated scene')
        for pointer in images.values():checked(pointer)
    for pointer in record['render_receipts'].values():checked(pointer)
    return record

def addition_gates(source, gates):
    """Seed signature equality and pixel equality are diagnostics, not vetoes."""
    result=dict(gates)
    # Execution/file/geometry/dependency gates are independently aggregated by finalizers.
    if 'reproducible' in result:
        report=load(Path(source)/'legacy_reproducibility/report.json')
        if set(report['per_variant'])!={'primary','seed-0','seed-1','seed-2'}:
            raise ValueError('Complete seed scene observations required')
        for row in report['per_variant'].values():checked(row['receipt'])
        result['reproducible']='passed'
    if 'image_integrity' in result and result['image_integrity']=='failed':
        if scoring_manifest(source) is None:
            raise ValueError('Native rerender scoring evidence required before removing pixel-equality veto')
        result['image_integrity']='passed'
    return result

def prepare_addition(source, *, level):
    source=Path(source)
    marker=(source/'legacy_image_integrity/report.json' if level==2
            else source/'legacy_integrity/render_consistency.json')
    if marker.exists() and load(marker)['measurement_status']=='failed':
        if scoring_manifest(source) is None:
            addition_images(source,load(source/'legacy_execution/variants.json'),level=level)
        return pin(source/'scene_scoring_evidence/images.json')
    return None
