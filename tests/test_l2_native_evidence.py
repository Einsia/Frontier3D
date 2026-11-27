"""Non-default seeds and per-variant lighting evidence use real pipeline gates."""
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

from PIL import Image
import pytest

from benchmark.resources import ROOT
from harness.L2.vlm_judge import JudgeConfig
from orchestrator.tasks import write_json
from tools.evaluate_linear_candidate import pin, artifact_variants
from tools.l2_seed_evidence import native_audits
from tools.lighting_edit_evidence import observation, prepare, VERSION, EVIDENCE_PATH


@pytest.fixture
def native_run(tmp_path):
    def build(task_id):
        root = tmp_path / 'campaign'
        run = root / 'native'
        task = root / 'inputs/data/3dbench/tasks' / task_id
        original = ROOT / 'data/3dbench/tasks' / task_id
        task.mkdir(parents=True)
        (task / 'instruction.md').write_bytes((original / 'instruction.md').read_bytes())
        spec = json.loads((original / 'harness/eval_spec.json').read_text())
        write_json(task / 'harness/eval_spec.json', spec)
        write_json(run / 'configuration/eval_spec.json', spec)
        files = ['harness/eval_spec.json', 'instruction.md']
        if spec.get('baseline_scene'):
            initial = task / spec['baseline_scene']
            initial.parent.mkdir(parents=True, exist_ok=True)
            initial.write_bytes(b'synthetic initial scene; no Blender execution')
            files.append(spec['baseline_scene'])
        before = {'objects': {'Light': {'type': 'LIGHT', 'location': [0, 0, 2], 'data_sha256': 'old'}},
                  'light_data': {'Light': {'settings': {'energy': 10, 'color': [.1, .2, 1]}, 'nodes': None}},
                  'world_data': None, 'world_sha256': 'world', 'render_settings_sha256': 'render',
                  'render': {'exposure': 0, 'gamma': 1}, 'saved_frame': 1}
        write_json(run / 'initial-inspection/output/facts.json', {'scene': before})
        manifest = {'task_id': task_id, 'spec_sha256': 'fixture-spec', 'model_call': True,
                    'seeds': spec['seeds'], 'attempts': {}, 'source_sha256': {},
                    'report_path': str(run / 'automatic.json'), 'evidence_path': str(run / 'grading-evidence.json'),
                    'implementation_unchanged': True}
        variants = {}
        for index, label in enumerate(['baseline', *(f'seed-{s}' for s in spec['seeds'])]):
            output = run / ('submission' if label == 'baseline' else label + '/attempt-00/output')
            output.mkdir(parents=True)
            (output / 'scene.blend').write_bytes(('synthetic scene ' + label).encode())
            for name in ['main.png', 'alternate.png']:
                Image.new('RGB', (8, 8), 'white').save(output / name)
            current = {p.name: pin(p) for p in output.iterdir()}
            variants['primary' if label == 'baseline' else label] = current
            manifest['attempts'][label] = [{'status': 'success', 'workspace': str(output.parent),
                                           'artifact_sha256': {k: v['sha256'] for k, v in current.items()}}]
            after = deepcopy(before)
            after['light_data']['Light']['settings']['energy'] = 100 + index
            after['objects']['Light']['data_sha256'] = 'new-' + label
            write_json(run / (label + '-inspection/output/facts.json'), {'scene': after})
            audit = {'execution_passed': True, 'audit': {'passed': True}, 'reproduction_matches_baseline': True,
                     'rerender': {'status': 'measured', 'passed': True, 'views': {
                         name: {'render_path': current[name]['path']} for name in ['main.png', 'alternate.png']}}}
            write_json(run / 'audit' / (label + '.json'), audit)
        primary = variants['primary']
        write_json(run / 'automatic.json', {'automatic_profile': 'l2-brief-embodied-v4.0.0',
                   'gates': {k: {'passed': True} for k in ['execution', 'integrity', 'all_seeds']},
                   'score_components': {'data': .5, 'physics': .5}, 'artifact_sha256': {}})
        write_json(run / 'grading-evidence.json', {'harness': {'seed_runs': {}}, 'artifacts': primary, 'artifact_sha256': {}})
        record = {'task_id': task_id, 'spec_sha256': 'fixture-spec', 'submission': str(run / 'submission'),
                  'artifact_sha256': {k: v['sha256'] for k, v in primary.items()},
                  'task_files_sha256': {name: pin(task / name)['sha256'] for name in files},
                  'evidence_sha256': {str(p.relative_to(run)): pin(p)['sha256'] for p in run.rglob('*') if p.is_file()}}
        write_json(run / 'execution_record.json', record)
        write_json(run / 'run.json', manifest)
        write_json(root / 'campaign.json', {'frozen': str(root / 'inputs'), 'provider_transport': 'https://offline.invalid'})
        row = {'task_id': task_id, 'status': 'completed', 'run_dir': str(run),
               'spec_sha256': 'fixture-spec', 'instruction_sha256': pin(task / 'instruction.md')['sha256']}
        write_json(root / 'fixture/batch.json', {'cases': [row]})
        return SimpleNamespace(root=root, run=run, task=task, task_id=task_id, manifest=manifest,
                               record=record, variants=variants, before=before, row=row)
    return build


@pytest.mark.parametrize('number', ['001', '010'])
def test_baseline_reaches_rescore_with_bound_default_or_date_seeds(native_run, monkeypatch, number):
    from tools import run_effort_l2_baseline as baseline
    case = native_run('L2/Brief2Scene/task_L2_Brief2Scene_' + number)
    monkeypatch.setattr(baseline, 'tested_model', lambda *a: 'fixture')
    monkeypatch.setattr(baseline, 'read_public_methods', lambda: [{'id': case.task_id, 'method_version': 'fixture'}])
    monkeypatch.setattr(baseline.JudgeConfig, 'from_env', lambda *a: JudgeConfig(model='gpt-6-astra'))
    monkeypatch.setattr(baseline, 'judge_key', lambda: 'offline-unused')
    calls = []
    def rescore(*args, **kwargs):
        calls.append(args)
        return {'method_version': 'fixture', 'source_bindings': {}, 'S_core': .5}
    monkeypatch.setattr(baseline, 'rescore', rescore)
    assert baseline.run(case.root, case.task_id)['S_core'] == .5
    assert len(calls) == 1


def test_date_seed_rerenders_and_reassessment_preserve_complete_population(native_run, monkeypatch):
    from tools.scene_scoring_evidence import native_images
    from tools.reassess_scene_content import prepare as reassess
    import src.evaluator.l2_case as case_module
    import src.evaluator.l2_method_scoring as method_module
    case = native_run('L2/Brief2Scene/task_L2_Brief2Scene_010')
    images = native_images(case.run)
    assert set(images['variants']) == {'primary', 'seed-20260914', 'seed-20260915', 'seed-20260916'}
    assert all(images['variants'][key]['scene.blend'] == value['scene.blend'] for key, value in case.variants.items())
    policy = {'task_id': case.task_id, 'automatic_profile': 'l2-brief-embodied-v4.0.0'}
    monkeypatch.setattr(case_module, 'load_case', lambda *a: ({}, SimpleNamespace(digest='fixture-spec'), policy))
    monkeypatch.setattr(method_module, 'load_methods', lambda *a: {})
    report, evidence = reassess(case.task, case.run, case.root / 'reassessment')
    assert json.loads(report.read_text())['S_core'] == pytest.approx(.5)
    assert set(json.loads(evidence.read_text())['harness']['seed_runs']) == {'20260914', '20260915', '20260916'}
    receipt = json.loads(report.with_name('policy-receipt.json').read_text())
    assert set(receipt['audit_receipts']) == {'baseline', 'seed-20260914', 'seed-20260915', 'seed-20260916'}


@pytest.mark.parametrize('damage', ['manifest_seeds', 'audit_bytes', 'missing_audit', 'task_seeds'])
def test_seed_validation_never_skips_missing_or_changed_evidence(native_run, damage):
    case = native_run('L2/Brief2Scene/task_L2_Brief2Scene_010')
    if damage == 'manifest_seeds':
        write_json(case.run / 'run.json', {**case.manifest, 'seeds': [0, 1, 2]})
    elif damage == 'task_seeds':
        p = case.task / 'harness/eval_spec.json'
        write_json(p, {**json.loads(p.read_text()), 'seeds': [0, 1, 2]})
    else:
        p = case.run / 'audit/seed-20260916.json'
        p.unlink() if damage == 'missing_audit' else p.write_text('{}')
    with pytest.raises((ValueError, FileNotFoundError)):
        native_audits(case.run, task=case.task)


@pytest.mark.parametrize('number', ['003', '005'])
def test_lighting_evidence_uses_each_variants_bound_facts(native_run, number):
    case = native_run('L2/SceneEdit/task_L2_SceneEdit_' + number)
    values = []
    for variant, artifacts in case.variants.items():
        pointer = prepare(case.run, case.task, case.task_id, variant, artifacts['scene.blend'], case.root / 'lighting' / variant)
        doc = json.loads(Path(pointer['path']).read_text())
        assert doc['policy'] == VERSION and doc['candidate_code_executed'] is False
        assert doc['before']['light_data']['Light']['settings']['energy'] == 10
        values.append(doc['candidate']['light_data']['Light']['settings']['energy'])
        assert doc['source_sha256']['candidate_scene'] == artifacts['scene.blend']['sha256']
        assert str(case.root) not in json.dumps(doc)
        assert prepare(case.run, case.task, case.task_id, variant, artifacts['scene.blend'], case.root / 'lighting' / variant) == pointer
    assert values == [100, 101, 102, 103]


@pytest.mark.parametrize('damage', ['wrong_variant', 'changed_facts', 'missing_facts', 'missing_parameters'])
def test_lighting_missingness_and_provenance_fail_before_judging(native_run, damage):
    case = native_run('L2/SceneEdit/task_L2_SceneEdit_003')
    scene = case.variants['seed-0' if damage == 'wrong_variant' else 'primary']['scene.blend']
    facts = case.run / 'baseline-inspection/output/facts.json'
    if damage == 'missing_facts':
        facts.unlink()
    elif damage in ['changed_facts', 'missing_parameters']:
        data = json.loads(facts.read_text())
        data['scene'].pop('light_data')
        write_json(facts, data)
        if damage == 'missing_parameters':
            record = deepcopy(case.record)
            record['evidence_sha256'][str(facts.relative_to(case.run))] = pin(facts)['sha256']
            write_json(case.run / 'execution_record.json', record)
    with pytest.raises((ValueError, FileNotFoundError)):
        observation(case.run, case.task, case.task_id, 'primary', scene)


def test_lighting_finalization_requires_native_packet_binding(native_run):
    from tools.lighting_edit_evidence import verify_detail
    case = native_run('L2/SceneEdit/task_L2_SceneEdit_003')
    pointer = prepare(case.run, case.task, case.task_id, 'primary', case.variants['primary']['scene.blend'], case.root / 'lighting')
    judge = case.root / 'judge/run.json'
    packet = judge.parent / 'packet'
    target = packet / EVIDENCE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(Path(pointer['path']).read_bytes())
    write_json(packet / 'manifest.json', {'sha256': {EVIDENCE_PATH: pointer['sha256']}})
    write_json(judge.parent / 'issues.json', {'checks': [{'check_id': 'edit_effect_5', 'evidence': [{'file': EVIDENCE_PATH}]}]})
    write_json(judge, {'source_bindings': {pointer['path']: pointer['sha256']},
                      'response_sha256': pin(judge.parent / 'issues.json')['sha256'],
                      'packet_sha256': pin(packet / 'manifest.json')['sha256']})
    detail = {'source_bindings': {'lighting_edit_evidence_policy': VERSION},
              'judge_runs': {'primary': pin(judge)}, 'lighting_edit_evidence': {'primary': pointer}}
    verify_detail(case.run, case.task, case.task_id, detail)
    target.write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        verify_detail(case.run, case.task, case.task_id, detail)
    with pytest.raises(ValueError, match='native evidence policy'):
        verify_detail(case.run, case.task, case.task_id, {'source_bindings': {}})


def test_lighting_images_alone_cannot_satisfy_new_native_evidence_obligation():
    from tools.lighting_edit_evidence import require_citation
    with pytest.raises(ValueError, match='must cite'):
        require_citation({'checks': [{'check_id': 'edit_effect_5', 'evidence': [{'file': 'candidate/main.png'}]}]})


@pytest.mark.parametrize('cite_native', [True, False])
def test_native_lighting_observations_reach_actual_single_round_request(native_run, monkeypatch, cite_native):
    from harness.L2.vlm_judge import judge_task
    from src.agent_judge import responses_runtime
    from src.agent_judge.detail_spec import project_detail_spec
    from tools.lighting_edit_evidence import verify_detail
    case = native_run('L2/SceneEdit/task_L2_SceneEdit_003')
    primary = case.variants['primary']
    pointer = prepare(case.run, case.task, case.task_id, 'primary', primary['scene.blend'], case.root / 'lighting')
    policy = json.loads((ROOT / 'configs/release/legacy-policy.json').read_text())
    recipe = next(r for r in policy['cases'] if r['task_id'] == case.task_id)
    source = ROOT / 'configs/release' / recipe['source_plan']['path'].removeprefix('@resource/')
    spec = project_detail_spec(json.loads(source.with_name('judge_spec.json').read_text()), recipe['criterion_ids'])
    # Synthetic test images are used only to exercise packet/request transport.
    spec['reference_bindings'] = {name: primary['main.png']['sha256'] for name in spec['reference_bindings']}
    frozen = {'_vlm_judge': {'version': 'continuous-task-judge-v1', 'mode': 'interactive',
                            'spec': spec, 'spec_sha256': 'offline-fixture',
                            'edit_context': {role: primary['main.png'] for role in ['before', 'target']}}}
    evidence = {'artifacts': primary, 'reference_images': {'main': primary['main.png']},
                'lighting_edit_evidence': pointer}
    home = case.root / 'auth-fixture'
    home.mkdir()
    (home / 'config.toml').write_text('model_provider="offline"\n[model_providers.offline]\nbase_url="https://offline.invalid/v1"\nwire_api="responses"\n')
    class FixtureRenderTool:
        """Replace only Blender rendering with labeled synthetic test images."""
        def __init__(self, script, config):
            self.config = json.loads(Path(config).read_text())
            self.generated = Path(self.config['private']) / 'generated'
            self.ledger = {'sources': self.config['scenes'], 'calls': [], 'sha256': {},
                           'worker_sha256': pin(self.config['worker'])['sha256'],
                           'test_only': 'Synthetic renders; no Blender execution'}
        def close(self): pass
        def request(self, method, params=None):
            if method == 'tools/list':
                return {'tools': [{'name': 'render_view', 'description': 'Synthetic fixture render',
                                   'inputSchema': {'type': 'object', 'properties': {}}}]}
            assert method == 'tools/call' and params['name'] == 'render_view'
            role = params['arguments']['scene'].split('/')[0]
            name = f'{role}/judge_generated/{len(self.ledger["calls"]) + 1:03d}.png'
            image = self.generated / name
            image.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(primary['main.png']['path'], image)
            target = Path(self.config['workspace']) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image, target)
            self.ledger['sha256'][name] = pin(image)['sha256']
            self.ledger['calls'].append({'status': 'success', 'tool': 'render_view',
                                         'arguments': params['arguments'], 'files': [name]})
            write_json(self.generated / 'manifest.json', self.ledger)
            return {'content': [{'type': 'text', 'text': 'Synthetic fixture image: ' + name}]}
    monkeypatch.setattr(responses_runtime, 'ToolServer', FixtureRenderTool)
    sent = []
    def send(request, **kwargs):
        payload = json.loads(request.data)
        sent.append(payload)
        prompt = payload['input'][1]['content'][0]['text']
        assert 'BEGIN ' + EVIDENCE_PATH in prompt
        assert '"energy": 100' in prompt and '"energy": 10' in prompt
        assert payload['tools'] == [] and payload['tool_choice'] == 'none'
        assert str(case.root) not in prompt
        checks = []
        for check in spec['checks']:
            files = list(check['required_evidence'])
            if check['id'] == 'edit_effect_5' and cite_native: files.append(EVIDENCE_PATH)
            checks.append({'check_id': check['id'], 'coverage': .5, 'deviation': .2, 'confidence': .5,
                           'evidence_status': 'demonstrated', 'achieved': 'Synthetic test observation',
                           'discrepancies': 'Synthetic test limitation',
                           'evidence': [{'file': name, 'bbox': None, 'observation': 'Test transport only'} for name in files]})
        answer = {'protocol': spec['protocol'], 'case_id': case.task_id, 'evidence_status': 'complete',
                  'evidence_reason': 'Offline transport fixture', 'checks': checks, 'summary': 'Not a benchmark result'}
        response = {'id': 'offline-response', 'status': 'completed',
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(answer)}]}],
                    'usage': {'input_tokens': 10, 'output_tokens': 5}}
        class Wire(io.BytesIO):
            status = 200
        return Wire(('data: ' + json.dumps({'type': 'response.completed', 'response': response}) + '\n\n').encode())
    monkeypatch.setattr(responses_runtime.urllib.request, 'urlopen', send)
    config = JudgeConfig(model='gpt-6-astra', codex_home=home, api_key='offline-unused',
                         base_url='https://offline.invalid/v1', engine='responses', attempts=1,
                         responses_options={'max_rounds': 1, 'preload_render_roles': True,
                                            'response_cache': str(case.root / 'response_cache')})
    output = case.root / 'judge'
    result = judge_task(case.task, evidence, frozen, output, config=config,
                        tested_model='fixture', blender=Path('/unused-offline-blender'))
    assert len(sent) == 1
    cached = list((case.root / 'response_cache').glob('*.json'))
    if not cite_native:
        assert result['status'] == 'not_measurable' and not cached
        assert 'must cite' in (output / 'attempt-1/stderr.log').read_text()
        return
    assert result['status'] == 'scored', result.get('reason')
    assert len(cached) == 1
    manifest = json.loads((output / 'packet/manifest.json').read_text())
    assert manifest['sha256'][EVIDENCE_PATH] == pointer['sha256']
    verify_detail(case.run, case.task, case.task_id,
                  {'source_bindings': {'lighting_edit_evidence_policy': VERSION},
                   'lighting_edit_evidence': {'primary': pointer}, 'judge_runs': {'primary': pin(output / 'run.json')}})
