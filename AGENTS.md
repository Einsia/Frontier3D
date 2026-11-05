# Running Frontier3D

Use the repository root and `python -m benchmark` for public generation and
evaluation. The release contains 145 tasks: 65 L1, 65 L2, and 15 L3. Start with
the installation and configuration steps in [docs/installation.md](docs/installation.md); detailed
documents are in [docs/README.md](docs/README.md).

## Check a new checkout

Use Python 3.13 in a virtual environment, install `requirements-dev.txt`, and
retrieve Git LFS assets with `git lfs pull`. Then run:

```sh
python -m benchmark list
python -m benchmark doctor --resources-only
python scripts/verify_release.py
python -m pytest -q
(cd harness/L3/release/codebase && python -m pytest tests/l3 --noconftest -q)
```

These checks make no model calls. For a focused offline test of all 145 task
selections, staged campaigns, failure continuation, resume, and result export:

```sh
python -m pytest tests/test_batch_cli.py tests/test_campaign_recovery.py -q
```

The batch test substitutes generation and evaluation bodies. Staging tests load
the real public inputs for all 130 Blender tasks and construct generation
requests; recovery tests substitute model processes and public Blender execution. Their synthetic
reports are test fixtures and must never be published as benchmark results.
Test the real Docker/Blender installation separately:

```sh
python scripts/smoke_offline.py --blender "$THREEDBENCH_BLENDER" \
  --output /tmp/frontier3d-smoke
```

Use a fresh smoke output path. This creates synthetic geometry and performs
real save, render, and export operations without calling a model service.

## Run a requested measurement

Configure the user's provider and runtime in an ignored `.env` file. Inspect
`.env.example` for supported settings; never print API keys or copy private
configuration into tracked files. Run `doctor` for the selected levels before
generation:

```sh
python -m benchmark doctor --level 1 2
python -m benchmark run --task L1/Text2Code/task_L1_Text2Code_001 \
  --output runs/my-model-text001
```

Use `--level 3` for UE checks. L3 requires the licensed engine, separate writable
candidate/evaluator engine copies, NVIDIA/Vulkan, and locked offline libraries
described in [L3 setup](docs/installation.md#configure-l3-ue). An unfiltered `--all` includes L3.

Keep `GENERATOR_RUNTIME=docker` for measured candidates. Only task requirements,
declared assets and runtime interfaces belong in model input. Grading notes and
task-source notices stay in organizer `harness/`, `solution/` and `attribution/`
directories. Local generation has host file access and is for trusted diagnostics.

Use `generate` and `evaluate` to separate the stages. Use `--resume` on an
existing campaign after inspecting failures. Accepted source, task inputs, and
completed reports are bound to hashes; configuration changes require a fresh
output directory. Keep failed logs and evidence. Docker is the default for
candidate execution; local execution is for trusted source.

Check the process exit status, `benchmark.json`, and final report validity.
Resource checks and offline tests establish their stated scope; complete online
generation, visual judging, and UE execution require real configured services.
Do not alter frozen scoring contracts, weights, references, budgets, or task
instructions to make a candidate pass. Do not replace failed generations with
fixtures or missing measurements with invented scores.
