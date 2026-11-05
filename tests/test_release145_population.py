"""Active population, attribution and L3 input classification agree on disk."""
import hashlib
import json
from collections import Counter

from benchmark.resources import ROOT


def test_release_population_and_collection_are_the_same_complete_manifest_set():
    collection = json.loads((ROOT/'data/3dbench/tasks/collection.json').read_text())
    mapping = json.loads((ROOT/'configs/release/task-id-map.json').read_text())
    rows = collection['tasks']
    ids = {r['task_id'] for r in rows}
    disk = {str(p.parent.relative_to(ROOT/'data/3dbench/tasks'))
            for level in ('L1', 'L2', 'L3')
            for p in (ROOT/'data/3dbench/tasks'/level).rglob('task.toml')}
    assert len(rows) == len(ids) == 145
    assert ids == disk
    assert ids == {r['new_task_id'] for r in mapping['tasks']}
    assert Counter(r['level'] for r in rows) == {1: 65, 2: 65, 3: 15}
    assert [r['release_id'] for r in rows] == [f'3DBench-{i:03d}' for i in range(1, 146)]
    assert not (ROOT/'data/3dbench/tasks/L1/CodeEdit').exists()
    for row in mapping['tasks']:
        manifest = ROOT/row['active_public_directory']/'task.toml'
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == row['active_task_toml_sha256']


def test_l3_category_migration_preserves_native_identity_and_real_reference_files():
    rows = json.loads((ROOT/'harness/L3/release/task-index.json').read_text())
    migration = json.loads((ROOT/'configs/release/l3-input-category-map.json').read_text())['tasks']
    assert len(rows) == len(migration) == 15
    assert Counter(r['category'] for r in rows) == {'Text2Environment': 5, 'Image2Environment': 10}
    images = 0
    for row, move in zip(rows, migration):
        assert row['task_key'] == move['task_key']
        assert row['release_task_id'] == move['new_task_id']
        assert move['old_task_id'] in row['legacy_task_ids']
        base = ROOT/row['path']
        inputs = base/'environment/input'
        refs = json.loads((inputs/'references.json').read_text())
        assert refs['input_mode'] == move['input_mode']
        assert row['category'] == ('Image2Environment' if refs['images'] else 'Text2Environment')
        images += len(refs['images'])
        for reference in refs['images']:
            image = inputs/reference['path']
            assert hashlib.sha256(image.read_bytes()).hexdigest() == reference['sha256']
        package = json.loads((base/'package-manifest.json').read_text())
        for name, expected in package['files'].items():
            assert hashlib.sha256((base/name).read_bytes()).hexdigest() == expected
    assert images == 24  # Public input population; frozen v5 bindings remain 23.
