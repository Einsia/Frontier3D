# L3 implementation and Harbor integration

L3 installation, environment configuration, asset preparation, generation,
evaluation, resume and CSV export are documented in the
[installation guide](../../../docs/installation.md#configure-l3-ue). Use the same
`python -m benchmark` interface for L1, L2 and L3. `run.py` is an internal adapter
for the nested L3 source layout; users do not need a separate entry point.

The 15 public wrappers are in `data/3dbench/tasks/L3/Text2Environment/` (5 tasks) and
`data/3dbench/tasks/L3/Image2Environment/` (10 tasks). Native task
schemas, the UE observer, generator and measurements live under `codebase/`.
`task-index.json` maps release task IDs to unchanged native task keys.
`scoring-specs/` contains the frozen v5 rubric and task-relative reference hashes.
`asset-locks/` retains acquisition metadata and original Kenney CC0 archives.

## Harbor integration

Each public task supplies Harbor schema 1.4 `task.toml`, an environment
Dockerfile and `tests/test.sh`. Its build requires an explicit
`L3_RUNTIME_IMAGE` containing a provisioned UE authoring workspace. A normal
Docker-only Harbor worker cannot provide the complete UE verifier by itself.

Provision a trusted host verifier with Docker/GPU access and identical trial,
engine and code paths. Set `L3_PYTHON`, `L3_RELEASE_ROOT`, `L3_TRIAL`, `L3_ENGINE`,
`L3_MODEL`, `L3_EFFORT`, `L3_JUDGE_PROVIDER`, optionally `L3_GPU` and
`L3_VERIFY_OUTPUT`, then run the task's `tests/test.sh`. `harbor_entry.py` calls
the same `verify.py` used by the native runner. The verifier checks frozen source
before and after scoring and writes `/logs/verifier/reward.txt = score_100/100`.
Use a fresh verifier directory and reward path for each run.

## Verification scope

Source/schema checks, all 23 reference bindings, fresh campaign initialization,
unified CLI dispatch, source/report cache integrity and score aggregation have
offline regression coverage. These checks do not establish a new-host UE/GPU
execution. The engine, drivers, downloaded libraries and paid model services
remain host prerequisites. See [runtime requirements](../../../docs/README.md#requirements) and
[experiment contract](../../../docs/en/experiment.md).

The scoring protocol and native task keys are unchanged. Release directories use
`Text2Environment/task_L3_Text2Environment_001` through `005`, and
`Image2Environment/task_L3_Image2Environment_001` through `010`; the overall score uses the frozen
L1/L2/L3=30/30/40 policy in [task aggregation](../../../docs/en/tasks.md).
