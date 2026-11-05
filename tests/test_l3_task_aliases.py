"""Keep in-flight campaigns usable when public L3 input categories change."""

import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from benchmark import l3

ROOT = Path(__file__).resolve().parents[1]


def test_explicit_legacy_identity_resolves_frozen_native_campaign(tmp_path, monkeypatch):
    release = tmp_path / "release"
    release.mkdir()
    old = "L3/Unified/task_L3_Unified_001"
    current = "L3/Image2Environment/task_L3_Image2Environment_001"
    record = {"task_key": "l3-e01", "release_task_id": current,
              "legacy_task_ids": [old, "L3/Unified/l3-e01"]}
    (release / "task-index.json").write_text(json.dumps([record]))
    output = tmp_path / "output"
    (output / "l3").mkdir(parents=True)
    native = {"task_key": "l3-e01", "output": "/retained/frozen-source"}
    (output / "l3/manifest.json").write_text(json.dumps({"rows": [native]}))
    monkeypatch.setattr(l3, "RELEASE", release)

    spec = importlib.util.spec_from_file_location("l3_release_alias_test", ROOT / "harness/L3/release/run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    runner.HERE = release
    for identity in [old, "L3/Unified/l3-e01", current, Path(current).name, "l3-e01"]:
        assert runner.canonical_task(identity) == "l3-e01"
        assert l3.canonical_task_key(identity) == "l3-e01"
        assert l3.native_row(identity, output) == native
    for unknown in ["L3/Unified/task_L3_Unified_002", "task_L3_Unified_001", "L3/Unknown/001"]:
        with pytest.raises(ValueError, match="Unknown L3 task identity"):
            runner.canonical_task(unknown)
        with pytest.raises(ValueError, match="Unknown L3 task identity"):
            l3.canonical_task_key(unknown)


def test_public_cli_selects_new_path_for_explicit_old_l3_id(tmp_path,monkeypatch):
    from benchmark import __main__ as cli
    monkeypatch.setenv('THREEDBENCH_ENV_FILE',os.environ.get('THREEDBENCH_ENV_FILE',''))
    seen=[]
    def execute(args,parser,options,output,tasks,rows):
        seen.extend(rows)
        assert args.task==['L3/Image2Environment/task_L3_Image2Environment_001']
        return 0
    monkeypatch.setattr(cli,'execute_campaign',execute)
    monkeypatch.setattr(sys,'argv',['benchmark','generate','--task','L3/Unified/task_L3_Unified_001',
                                    '--output',str(tmp_path/'campaign'),'--model','gpt-6-luna'])
    assert cli.main()==0
    assert len(seen)==1 and seen[0]['category']=='Image2Environment'
