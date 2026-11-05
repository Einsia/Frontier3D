"""Synchronize task-owned L2 policy bundles from the authoritative harness tree."""
import argparse
import shutil
from pathlib import Path

from harness.L2.config import load_policy
from src.evaluator.spec import EvalSpec
from src.evaluator.l2_requirements import load_requirements

TASKS = ('Brief2Scene', 'Reference2Scene', 'SceneEdit')
FILES = ('harness.toml', 'eval_spec.json', 'requirements.json')


def synchronize(tasks_root, *, check=False, source=None):
    source = Path(source or Path(__file__).parent)
    problems = []
    for name in TASKS:
        task = Path(tasks_root)/'L2'/name
        spec = EvalSpec.load(source/name/'eval_spec.json')
        load_policy(source/name/'harness.toml','L2/'+name,spec)
        load_requirements(source/name/'requirements.json', spec, 'L2/'+name,(task/'instruction.md').read_text())
        for file in FILES:
            target = task/'harness'/file
            if not target.is_file() or target.read_bytes() != (source/name/file).read_bytes():
                problems.append(str(target))
                if not check:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source/name/file,target)
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks-root',type=Path,default=Path('data/3dbench/task'))
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args(argv)
    changes = synchronize(args.tasks_root,check=args.check)
    print(('Out of sync: ' if args.check else 'Synchronized: ')+str(len(changes)))
    return int(args.check and bool(changes))


if __name__ == '__main__':
    raise SystemExit(main())
