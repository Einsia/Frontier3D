from __future__ import annotations
import argparse, json
from pathlib import Path
from harness.common.runner import run_trial

def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Run an L3 Codex harness generation trial")
    p.add_argument("--task", required=True); p.add_argument("--tasks-root", type=Path, default=Path("data/3dbench/task")); p.add_argument("--harness-config", type=Path, required=True); p.add_argument("--output-dir", type=Path, default=Path("data/task_runs")); p.add_argument("--env-file", type=Path); p.add_argument("--trial-id", default="0")
    a=p.parse_args(argv)
    try: result=run_trial(task_id=a.task, tasks_root=a.tasks_root, config_path=a.harness_config, output_dir=a.output_dir, level=3, task_prefix="L3/", env_file=a.env_file, trial_id=a.trial_id)
    except (OSError, ValueError, RuntimeError) as e: print(f"[l3-harness] error: {e}"); return 1
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0
if __name__ == "__main__": raise SystemExit(main())
