"""Catch stale task paths and edited dependency bytes inside the L3 inventory."""

import hashlib
import json

import pytest

from scripts.verify_release import source_inventory_errors


@pytest.mark.parametrize('change',['none','moved','edited','outside','duplicate'])
def test_source_inventory_validates_paths_bytes_and_population(tmp_path,change):
    file=tmp_path/'input.txt';file.write_text('fixed input\n')
    row={'path':'input.txt','bytes':file.stat().st_size,
         'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    rows=[row]
    if change=='moved':file.rename(tmp_path/'new-input.txt')
    elif change=='edited':file.write_text('edited bytes\n')
    elif change=='outside':row['path']='../input.txt'
    elif change=='duplicate':rows.append(dict(row))
    inventory=tmp_path/'harness/L3/release/source-manifest.json'
    inventory.parent.mkdir(parents=True)
    inventory.write_text(json.dumps({'files':rows,'count':len(rows)}))
    errors=source_inventory_errors(tmp_path)
    assert bool(errors)==(change!='none')
