"""Image-main-score contracts: no submitted-PNG shortcut or background reward."""
import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.evaluator.l1 import score_l1
from src.evaluator.l1_image_pair import (
    appearance_arrays,
    consistency,
    image_pair,
    read_bound_image,
)
from src.evaluator.metrics import MissingEvidence, validate_metrics
from src.evaluator.spec import CheckSpec, EvalSpec

ROOT = Path(__file__).resolve().parents[1]


def arrays():
    image = np.full((64, 64, 4), 255, dtype=np.uint8)
    image[16:48, 16:48, :3] = [120, 40, 20]
    mask = np.zeros((64, 64), bool)
    mask[16:48, 16:48] = True
    regions = {'top': [[.2, .2, .8, .5]], 'bottom': [[.2, .5, .8, .8]]}
    return image, mask, regions


def test_identical_render_is_one_and_wrong_foreground_is_low():
    image, mask, regions = arrays()
    same = appearance_arrays(image, image, mask, mask, regions)
    assert same['score'] == pytest.approx(1)
    background = np.full_like(image, 255)
    assert appearance_arrays(background, image, np.zeros_like(mask), mask, regions)['score'] == 0
    different = image.copy()
    different[mask, :3] = [20, 40, 120]
    result = appearance_arrays(different, image, mask, mask, regions)
    assert result['score'] < .6
    assert result['regions']['top']['delta_e76_mean'] > 30


def test_geometry_not_colours_defines_mask_and_extra_geometry_costs():
    image, mask, regions = arrays()
    large = np.ones_like(mask)
    result = appearance_arrays(image, image, large, mask, regions)
    assert result['silhouette_iou'] == .25
    assert result['score'] == pytest.approx(.25)


def test_background_similarity_cannot_swamp_small_region():
    image, mask, regions = arrays()
    left = image.copy()
    left[16:32, 16:48, :3] = 255
    candidate_mask = mask.copy()
    candidate_mask[16:32] = False
    result = appearance_arrays(left, image, candidate_mask, mask, regions)
    assert result['regions']['top']['score'] == 0
    assert result['score'] <= .25


def test_no_resizing_or_empty_reference_region():
    image, mask, regions = arrays()
    with pytest.raises(ValueError, match='native pixel grid'):
        appearance_arrays(image[:32], image, mask[:32], mask, regions)
    with pytest.raises(ValueError, match='no visible geometry'):
        appearance_arrays(image, image, mask, mask, {'missing': [[0, 0, .1, .1]]})


def fixture(tmp_path):
    image, mask, regions = arrays()
    records = {}
    mask_rgba = np.zeros_like(image)
    mask_rgba[mask] = 255
    for name, pixels in [('native', image), ('submitted', image), ('reference', image), ('mask', mask_rgba)]:
        path = tmp_path / (name + '.png')
        Image.fromarray(pixels).save(path)
        records[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    raw = {
        'version': 'scalable-v1.1.0', 'profile': 'L1', 'mode': 'reference',
        'required_artifacts': ['scene.blend', 'main.png'], 'scene': 'scene.blend',
        'render_views': [{'id': 'primary', 'location': [1, -1, 1], 'target': [0, 0, 0],
                          'ortho_scale': 2, 'frame': 1, 'beauty': True, 'beauty_resolution': [64, 64], 'camera_source': 'saved'}],
        'reference_images': {'primary': 'reference.png'},
        'checks': {name: [{'id': name, 'group': name, 'metric': 'equals', 'params': {'path': '/yes', 'expected': True}}]
                   for name in ['spec', 'geometry', 'structure', 'visual', 'robust']},
    }
    pair = {'id': 'pair', 'group': 'pair', 'metric': 'native_image_pair', 'pass_threshold': 0,
            'params': {'view': 'primary', 'mask_asset': 'mask.png', 'mask_sha256': records['mask']['sha256'],
                       'reference_sha256': records['reference']['sha256'], 'regions': regions}}
    integrity = {'id': 'integrity', 'group': 'integrity', 'metric': 'main_render_consistency', 'params': {
        'view': 'primary', 'artifact': 'main.png', 'mean_tolerance': 2/255, 'p99_tolerance': 10/255}}
    raw['checks']['visual'].extend([pair, integrity])
    raw['critical_constraints'] = ['integrity']
    spec = EvalSpec.from_dict(raw)
    evidence = {'yes': True, 'scene': {'has_real_geometry': True}, 'harness': {'execution_passed': True},
                'artifacts': {'scene.blend': {'sha256': 'scene-hash', 'loadable': True},
                              'main.png': {'sha256': records['submitted']['sha256'], 'validation_io': records['submitted'], 'loadable': True}},
                'views': {'primary': {'render_protocol': 'l1-saved-camera-v1', 'source_sha256': 'scene-hash',
                                     'image': records['native']['path'], 'image_sha256': records['native']['sha256'],
                                     'mask': records['mask']['path'], 'mask_sha256': records['mask']['sha256'],
                                     'frame': 1, 'camera_source': 'saved', 'inspector_execution': {'fixture': True}}},
                'reference_images': {'primary': records['reference']}, 'image_reference_masks': {'primary': records['mask']}}
    return spec, evidence, CheckSpec.parse(pair), CheckSpec.parse(integrity)


@pytest.mark.parametrize('frame', [None, True, 61, '1'])
def test_saved_image_wrong_or_missing_frame_is_not_assembled_evidence(tmp_path, frame):
    spec, evidence, pair, integrity = fixture(tmp_path)
    evidence['views']['primary']['frame'] = frame
    for check, measure in [(pair, image_pair), (integrity, consistency)]:
        with pytest.raises(MissingEvidence, match='saved-render protocol'):
            measure(check, evidence, spec)


def test_primary_image_view_cannot_claim_exploded_frame(tmp_path):
    spec, _, _, _ = fixture(tmp_path)
    raw = spec.to_dict()
    raw['render_views'][0]['frame'] = 61
    with pytest.raises(ValueError, match='requires frame 1'):
        validate_metrics(EvalSpec.from_dict(raw))


def test_declared_view_has_distinct_protocol_and_exact_camera_binding(tmp_path):
    spec, evidence, pair, _ = fixture(tmp_path)
    raw = spec.to_dict()
    raw['checks']['visual'] = [c for c in raw['checks']['visual'] if c['metric'] != 'main_render_consistency']
    raw['critical_constraints'] = []
    raw['required_artifacts'] = ['scene.blend']  # No new PNG delivery requirement.
    raw['render_views'][0]['camera_source'] = 'declared'
    spec = EvalSpec.from_dict(raw)
    validate_metrics(spec)
    with pytest.raises(MissingEvidence, match='binding'):
        image_pair(pair,evidence,spec)
    capture = evidence['views']['primary']
    capture.update(camera_source='declared',render_protocol='l1-declared-camera-v1',
        camera_definition={k:raw['render_views'][0][k] for k in ('location','target','ortho_scale')})
    score,details = image_pair(pair,evidence,spec)
    assert score == pytest.approx(1) and details['camera_source'] == 'declared'
    capture['camera_definition']['ortho_scale'] *= 2
    with pytest.raises(MissingEvidence,match='frozen view'):
        image_pair(pair,evidence,spec)


def test_png_consistency_cannot_be_replaced_by_declared_view(tmp_path):
    spec,_,_,_ = fixture(tmp_path)
    raw = spec.to_dict()
    raw['render_views'][0]['camera_source'] = 'declared'
    with pytest.raises(ValueError,match='submitted-image contract'):
        validate_metrics(EvalSpec.from_dict(raw))
    raw['checks']['visual'] = [c for c in raw['checks']['visual'] if c['metric'] != 'native_image_pair']
    with pytest.raises(ValueError,match='submitted saved camera'):
        validate_metrics(EvalSpec.from_dict(raw))


@pytest.mark.parametrize('source',[[],{},1,False])
def test_invalid_camera_source_is_a_configuration_error(tmp_path,source):
    spec,_,_,_ = fixture(tmp_path)
    raw = spec.to_dict()
    raw['render_views'][0]['camera_source'] = source
    with pytest.raises(ValueError,match='Saved camera'):
        EvalSpec.from_dict(raw)


def test_pair_requires_native_source_and_unchanged_files(tmp_path):
    spec, evidence, pair, integrity = fixture(tmp_path)
    validate_metrics(spec)
    assert image_pair(pair, evidence, spec)[0] == pytest.approx(1)
    assert consistency(integrity, evidence, spec)[0] == 1
    evidence['views']['primary']['source_sha256'] = 'unrelated'
    with pytest.raises(MissingEvidence, match='binding'):
        image_pair(pair, evidence, spec)
    path = Path(evidence['reference_images']['primary']['path'])
    path.write_bytes(b'changed')
    with pytest.raises(MissingEvidence, match='changed'):
        read_bound_image(path, evidence['reference_images']['primary']['sha256'])


def test_copying_png_does_not_change_quality_and_fails_consistency(tmp_path):
    spec, evidence, pair, integrity = fixture(tmp_path)
    path = Path(evidence['views']['primary']['image'])
    pixels = np.full((64, 64, 4), 255, np.uint8)
    Image.fromarray(pixels).save(path)
    evidence['views']['primary']['image_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert consistency(integrity, evidence, spec)[0] == 0
    expected = image_pair(pair, evidence, spec)[0]
    assert expected < .3
    report = score_l1(spec, evidence)
    assert report['S_level'] == pytest.approx(expected)
    assert report['S_core'] == report['S_diagnostic'] == 0
    assert report['image_quality_policy']['base_checks_score'] == 1
    assert report['formal_score_eligible'] is False


def test_invalid_protocol_configuration_is_rejected(tmp_path):
    spec, _, _, _ = fixture(tmp_path)
    raw = spec.to_dict()
    raw['render_views'][0]['camera_source'] = 'invented'
    with pytest.raises(ValueError, match='Saved camera'):
        EvalSpec.from_dict(raw)
    raw = spec.to_dict()
    raw['checks']['visual'][1]['pass_threshold'] = .9
    with pytest.raises(ValueError, match='completion threshold'):
        validate_metrics(EvalSpec.from_dict(raw))
    raw = copy.deepcopy(spec.to_dict())
    raw['checks']['visual'][-1]['params']['p99_tolerance'] = float('nan')
    with pytest.raises(ValueError):
        validate_metrics(EvalSpec.from_dict(raw))
