"""Recover interrupted acceptance without model calls or mutable result caches."""
import json
import re
import shutil
import time
from pathlib import Path

import pytest

from benchmark import engine
from orchestrator import generator
from orchestrator.tasks import TASKS, load_task, sha256, write_json
from src.generator.client import GeneratorConfig

TASK = 'L1/Text2Code/task_L1_Text2Code_001'


@pytest.fixture
def generation(tmp_path, monkeypatch):
    tasks = tmp_path / 'tasks'
    shutil.copytree(TASKS / TASK, tasks / TASK)
    config = GeneratorConfig(api_key='offline-token', base_url='https://offline.invalid/v1', model='offline-fixture')
    calls = []

    def process(command, **kwargs):
        calls.append(command)
        response = Path(command[command.index('--output-last-message') + 1])
        response.write_text(json.dumps({
            'protocol': 'l1-submission-bundle-v1', 'entrypoint': 'solution.py',
            'files': [{'path': name, 'encoding': 'utf-8', 'content': content}
                      for name, content in [('solution.py', 'pass\n'), ('README.md', 'Offline fixture\n')]],
            'runtime': 'Blender Python', 'dependencies': [], 'run_instructions': 'offline test',
        }))
        kwargs['directory'].mkdir()
        return {'status': 'success'}

    monkeypatch.setattr(generator, 'run_process', process)
    monkeypatch.setattr(GeneratorConfig, 'from_env', lambda *a, **k: config)
    monkeypatch.setattr(engine, 'generation_validator', lambda *a, **k: lambda *a: [{'status': 'success'}])
    options = dict(tasks_root=str(tasks), effort='max', runtime='local', image='unused',
                   generator_runtime='local', execution_timeout=30, generation_timeout=30,
                   generation_total_timeout=300, attempts=6)
    return tmp_path / 'campaign', tasks, config, calls, options


def test_all_blender_tasks_stage_and_build_generation_requests(generation):
    """Real public inputs, prompts and bundle decoding; provider is a double."""
    from benchmark.__main__ import inventory
    root, _, config, calls, _ = generation
    rows = list(inventory())
    assert len(rows) == 130
    for row in rows:
        root.mkdir()
        source, history = generator.generate(
            load_task(row['task_id'], require_harness=False), root,
            deadline=time.monotonic() + 120, timeout=30, attempts=6,
            runtime='local', config=config,
        )
        assert history[-1]['status'] == 'success'
        assert (source / 'solution.py').read_text() == 'pass\n'
        prompt = json.loads((root / 'generation_context.json').read_text())['prompt']
        assert not re.search(r'Final item score|## Scoring|main_image|global_weight|not_measurable|"metric"\s*:', prompt)
        assert not any(path.name in {'CREDIT.txt', 'CREDITS', 'LICENSE.txt', 'SOURCE.txt'}
                       for path in (root / 'model-input').rglob('*'))
        shutil.rmtree(root)
    assert len(calls) == 130


@pytest.mark.parametrize('change', ['none', 'source', 'extra', 'response'])
def test_successful_generator_resumes_without_another_call(generation, change):
    root, tasks, config, calls, _ = generation
    root.mkdir()
    task = load_task(TASK, tasks)
    kwargs = dict(deadline=time.monotonic() + 30, timeout=30, attempts=6,
                  runtime='local', config=config, validate_submission=lambda *a: [{'status': 'success'}])
    source, history = generator.generate(task, root, **kwargs)
    if change == 'source':
        (source / 'solution.py').write_text('changed\n')
    elif change == 'extra':
        (source / 'extra.py').write_text('changed\n')
    elif change == 'response':
        (root / 'generation-00/response/bundle.json').write_text('{}')
    if change == 'none':
        assert generator.generate(task, root, resume=True, **kwargs) == (source, history)
    else:
        with pytest.raises(ValueError, match='changed'):
            generator.generate(task, root, resume=True, **kwargs)
    assert len(calls) == 1


def test_campaign_recovers_interrupted_source_snapshot(generation, monkeypatch):
    root, _, config, calls, options = generation
    original = engine.snapshot

    def interrupted(source, target, **kwargs):
        original(source, target, **kwargs)
        raise KeyboardInterrupt('simulated stop during source publication')

    monkeypatch.setattr(engine, 'snapshot', interrupted)
    with pytest.raises(KeyboardInterrupt):
        engine.generate(TASK, root, config.model, options)
    # Source publication needs no more generation time or model invocation.
    budget = root / 'jobs' / Path(TASK).name / 'generation/generation-budget.json'
    write_json(budget, {'status': 'stopped', 'consumed_seconds': options['generation_total_timeout']})
    monkeypatch.setattr(engine, 'snapshot', original)
    result = engine.generate(TASK, root, config.model, options)
    engine.verify_generated(result)
    assert len(calls) == 1
    assert engine.generate(TASK, root, config.model, options) == result


@pytest.mark.parametrize('change', ['instruction', 'harness', 'source-extra'])
def test_generated_cache_rejects_changed_inputs_and_source(generation, change):
    root, tasks, config, _, options = generation
    result = engine.generate(TASK, root, config.model, options)
    if change == 'instruction':
        path = tasks / TASK / 'instruction.md'
    elif change == 'harness':
        path = tasks / TASK / 'harness/eval_spec.json'
    else:
        path = Path(result['submission']) / 'extra.py'
    path.write_text('changed\n')
    with pytest.raises(ValueError, match='changed'):
        engine.generate(TASK, root, config.model, options)


@pytest.mark.parametrize('change', ['none', 'report', 'generation', 'identity'])
def test_report_cache_and_export_verify_receipt(generation, change):
    root, _, config, _, options = generation
    engine.generate(TASK, root, config.model, options)
    path = root / 'main_results' / config.model / Path(TASK).name / 'report.json'
    report = dict(task_id=TASK, model=config.model, S_core=.5, status='scored', score_valid=True)
    write_json(path, report)
    generated = root / 'jobs' / Path(TASK).name / 'generate-result.json'
    write_json(engine.report_receipt(root, TASK), {
        'report_sha256': sha256(path), 'generation_sha256': sha256(generated),
    })
    if change == 'report':
        write_json(path, {**report, 'S_core': .9})
    elif change == 'identity':
        write_json(path, {**report, 'task_id': TASK + '-changed'})
    elif change == 'generation':
        write_json(generated, {**json.loads(generated.read_text()), 'provided_source': True})
    from benchmark.export import export_scores
    if change == 'none':
        assert engine.evaluate(TASK, root, config.model, options) == report
        assert export_scores(root)['completed'] == 1
    else:
        with pytest.raises(ValueError, match='changed'):
            engine.evaluate(TASK, root, config.model, options)
        with pytest.raises(ValueError, match='changed'):
            export_scores(root)
