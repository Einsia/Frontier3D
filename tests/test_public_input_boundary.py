"""Candidate inputs contain requirements and assets, without organizer metadata."""
import importlib.util
import json
from pathlib import Path
import re
import tomllib

import pytest

from benchmark.resources import ROOT
from orchestrator.tasks import load_task
from src.generator.public_inputs import organizer_file, require_public_input


def test_every_blender_allowlist_and_instruction_excludes_organizer_information():
    files = list((ROOT / 'data/3dbench/tasks').glob('L[12]/*/*/task.toml'))
    assert len(files) == 130
    forbidden = re.compile(r'Final item score|## Scoring|## 评分|main_image|not_measurable|'
                           r'"metric"\s*:|global_weight|reference_feature_|IoU|SSIM|docs/(?:en|cn)/scoring')
    for meta in files:
        manifest = tomllib.loads(meta.read_text())
        task = load_task(manifest['id'], require_harness=False)
        assert all(not organizer_file(name) for name in manifest['environment_files'])
        for path in task.root.glob('instruction*.md'):
            assert not forbidden.search(path.read_text()), str(path)
        assert (task.root / 'attribution/CREDITS').is_file()
        assert not any(organizer_file(path.name) for path in (task.root / 'environment').rglob('*') if path.is_file())


@pytest.mark.parametrize('name', ['input/CREDIT.txt', 'input/CREDITS', 'input/CREADIT.md',
                                 'input/LICENSE.txt', 'input/SOURCE.txt', 'input/provenance.json',
                                 'input/attribution/notice.md'])
def test_attribution_cannot_be_reintroduced_into_allowlist(name):
    with pytest.raises(ValueError, match='Organizer metadata'):
        require_public_input(name)


def l3_stager():
    spec = importlib.util.spec_from_file_location('l3_input_stager', ROOT / 'harness/L3/release/codebase/tools/l3_public_inputs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l3_staging_removes_source_urls_even_from_legacy_manifests(tmp_path):
    stage = l3_stager()
    source, output = tmp_path / 'input', tmp_path / 'public'
    source.mkdir()
    (source / 'reference.png').write_bytes(b'local image')
    (source / 'references.json').write_text(json.dumps({'input_mode': 'image', 'images': [{
        'id': 'reference-01', 'path': 'reference.png', 'width': 800, 'height': 600,
        'sha256': '0' * 64, 'provenance': {'source': 'https://hidden.invalid/source'},
    }]}))
    (source / 'CREDIT.txt').write_text('https://hidden.invalid/source')
    (source / 'REFERENCES.md').write_text('https://hidden.invalid/source')
    stage.stage_public_inputs(source, output)
    assert not (output / 'CREDIT.txt').exists()
    assert 'provenance' not in (output / 'references.json').read_text()
    assert 'http' not in (output / 'REFERENCES.md').read_text()
    assert (output / 'reference.png').read_bytes() == b'local image'


def test_all_l3_reference_packages_keep_attribution_outside_inputs(tmp_path):
    stage = l3_stager()
    tasks = list((ROOT / 'data/3dbench/tasks/L3').glob('*/*'))
    tasks += [meta.parent for meta in (ROOT / 'harness/L3/release/codebase/tasks/L3').glob('*/task.json')
              if json.loads(meta.read_text()).get('execution_status') == 'generation_ready']
    assert len(tasks) == 30
    for index, task in enumerate(tasks):
        original = json.loads((task / 'attribution/references.json').read_text())
        public = json.loads((task / 'environment/input/references.json').read_text())
        assert public == stage.public_references(original)
        stage.stage_public_inputs(task / 'environment/input', tmp_path / str(index))
        for path in (tmp_path / str(index)).rglob('*'):
            if path.suffix in {'.md', '.txt', '.json'}:
                assert not re.search(r'https?://|"provenance"|Final item score|global_weight', path.read_text()), str(path)


def test_generator_does_not_read_private_harness_to_build_prompt():
    import inspect
    from orchestrator import generator
    source = inspect.getsource(generator)
    assert 'harness/eval_spec.json' not in source
    assert 'dimension_tolerance_m' not in source
    assert 'render_views' not in source


def test_public_example_uses_container_generation():
    from dotenv import dotenv_values
    assert dotenv_values(ROOT / '.env.example')['GENERATOR_RUNTIME'] == 'docker'
