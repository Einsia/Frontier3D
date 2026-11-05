# Installation and running

[Project overview](../README.md) · [Documentation](README.md) · [中文文档](cn/README.md)

Run all commands from the repository root. Follow the source, installation,
model harness and configuration sections first. Configure L3 before selecting
UE tasks or an unfiltered full campaign.

- [Get the source](#get-the-source)
- [Install Python and Blender](#install)
- [Model harnesses](#model-harnesses)
- [Configure providers](#configure)
- [Configure L3 / UE](#configure-l3-ue)
- [Generate and evaluate one task](#generate-and-evaluate-one-task)
- [Run the full collection](#run-the-full-collection)
- [Resume and inspect](#resume-and-inspect)
- [Validate](#validate)
- [Aggregate scores](#aggregate-l1l2l3-scores)

## Get the source

Install Git and Git LFS, clone the repository, and retrieve the real task assets:

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs
git lfs install
git clone https://github.com/Einsia/Frontier3D.git
cd Frontier3D
git lfs pull
```

Allow at least 10 GiB for the source checkout, plus external runtimes and run
output. Verify the complete checkout after installing the Python dependencies
below with `python scripts/verify_release.py`. LFS pointer files do not satisfy
the asset SHA-256 checks.

## Install

Use Linux x86-64, Python 3.13, Node.js 22+, Docker Engine, and Blender 5.2.1 LTS.
Install Python/venv, Node/npm and Docker first; the commands below do not install
those host runtimes. Your user must be able to run `docker info` successfully.
Run commands from the repository root (the directory containing the repository README).
The checkout contains
about 8 GiB of task assets and the fixed Kenney source archives; Git LFS is required for the published clone.
Keep this source checkout: task assets
and release contracts are loaded from it.

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Blender is an external executable; host Python does not need a bpy wheel.
Install Blender's shared libraries on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs curl xz-utils bubblewrap \
  libx11-6 libxrender1 libxfixes3 libxi6 libxkbcommon0 libsm6 libice6 \
  libgl1 libegl1 libegl-mesa0 libgl1-mesa-dri libgomp1 \
  libwayland-client0 libwayland-cursor0 libwayland-egl1
git lfs install
git lfs pull
```

Large reference scenes and models are task dependencies. Retrieve them with
`git lfs pull` after cloning.

Download Blender and verify the official checksum:

```bash
mkdir -p third_party
cd third_party
curl -fLO https://download.blender.org/release/Blender5.2/blender-5.2.1-linux-x64.tar.xz
curl -fLO https://download.blender.org/release/Blender5.2/blender-5.2.1.sha256
grep 'blender-5.2.1-linux-x64.tar.xz' blender-5.2.1.sha256 | sha256sum -c -
tar -xJf blender-5.2.1-linux-x64.tar.xz
cd ..
export THREEDBENCH_BLENDER="$PWD/third_party/blender-5.2.1-linux-x64/blender"
```

Build the candidate-execution image; Blender is mounted read-only at runtime:

```bash
docker build -t 3dbench-l1-blender:mvp -f orchestrator/Dockerfile.blender orchestrator
```

## Model harnesses

Generation uses the following model harnesses. Install the CLI needed by your
selected model:

| Models                        | Harness          | Provider API       |
| ----------------------------- | ---------------- | ------------------ |
| GPT                           | Codex            | Responses          |
| Claude, Qwen, MiniMax, Doubao   | Claude Code      | Anthropic Messages |
| GLM                           | zcode            | Chat Completions   |
| Kimi                          | Kimi codecli     | Chat Completions   |
| DeepSeek                      | DeepSeek Harness | Chat Completions   |
| Gemini                        | gemini-cli       | Native Gemini API  |

```bash
npm install --global @openai/codex@0.163.0
npm install --global @anthropic-ai/claude-code@2.1.268
npm install --global zcode-app-cli@3.16.3-40
npm install --global @moonshot-ai/kimi-code@2.3.2
npm install --global @deepseek-ai/dsh@0.2.1-rc.2
npm install --global @google/gemini-cli@0.67.0
```

Set the actual model ID and provider in `.env`. Omit `--effort` to use the
model's configured value: Qwen xhigh, Gemini high, other listed models max.
See [model configuration](en/models.md) for exact IDs and executable overrides.

L1/L2 generation defaults to Docker so the model sees only staged public inputs.
Build the selected harness image and keep `GENERATOR_RUNTIME=docker`:

```bash
# Build the image for the selected harness:
docker build -t 3dbench-codex:0.163.0 -f Dockerfile.codex .
docker build -t 3dbench-claude:2.1.268 -f Dockerfile.claude .
docker build -t 3dbench-native:contract-v1 -f Dockerfile.native .
```

The native image contains zcode, Kimi, DeepSeek and Gemini CLIs. For L3, install
the selected package into the external prefix used by `L3_NATIVE_CLI`; for example:

```bash
npm install --prefix /absolute/path/to/l3-cli @openai/codex@0.163.0
```

L3 keeps provider credentials on the host gateway. `doctor` checks the selected
CLI and its configuration without making model calls.

## Configure

```bash
cp .env.example .env
# Replace placeholder URLs, keys and OPENAI_MODEL; keep VLM_MODEL=gpt-6-astra.
# Optionally set THREEDBENCH_BLENDER here instead of exporting it above.
python -m benchmark doctor --level 1 2
python -m benchmark list
```

Use the provider API required by the selected harness in the table above.
Image tasks require image input. The frozen default judge is gpt-6-astra at medium effort. Several compact
scoring adapters currently fix this model ID. Changing VLM_MODEL alone is not
sufficient to switch every path; see [judge configuration limits](en/results.md#judge-configuration).
Record the actual judge ID with results: changing the judge changes evaluation.
Model IDs are not assumed available on every provider.

OPENAI_* configures generation; VLM_* independently configures judging.
Use the canonical Claude model ID claude-opus-5-5; see [model identities](en/models.md).
Keys are used only at runtime. No working key or private relay is shipped. The example .env is not a working configuration.
Use --env-file /path/to/config.env for another configuration.
`GENERATOR_RUNTIME` in the env file selects local or Docker generation; an
explicit `--generator-runtime` takes precedence. Local generation has host file
access and is intended for trusted diagnostics. Provider values in the chosen
env file override inherited provider settings. Blender selection is `--blender`,
then exported `THREEDBENCH_BLENDER`, then the chosen env file, then the bundled
checkout location under `third_party/`. Relative Blender paths in the env file
are resolved against that file's directory; `~` is supported.

`doctor` returns **0** only when the offline checks pass and **2** when required
configuration or runtimes are missing. It rejects example credentials/URLs,
unsupported judge IDs and incorrect Blender/Codex versions, checks the selected
Docker images, and validates all L1/L2 inputs plus L3 packages/reference bindings.
It reports credential presence without printing keys and makes no model calls.
API/model availability still needs an online run. `doctor --resources-only`
skips credentials and external runtimes. Use `--level 1 2` for Blender-only host
checks, `--level 3` for UE-only host checks, or omit `--level` to check all three
levels. L3 setup is described in the next section.

## Configure L3 (UE)

L3 uses the same `.env` and `python -m benchmark` commands as L1/L2. Its 15
Text2Environment/Image2Environment tasks, UE observer plugin, generation code, frozen v5 scoring specs and
23 reference-image bindings are included. Install the following host dependencies
before running `--level 3` or an unfiltered `--all` campaign:

1. A licensed, built **Unreal Engine 5.8.3** for Linux x86-64 matching
   [the engine lock](../harness/L3/release/codebase/ue5/engine-lock.json).
   Set `L3_UE_ROOT` to its original build location. Make two separate writable
   engine copies for candidate generation and trusted evaluation. The runner
   binds each copy to the original build path. Do not use hard links to share
   writable engine files.
   Keep editor binaries, engine headers/libraries, UnrealBuildTool, Build.sh
   and the bundled v26 Clang 20.1.8 Linux SDK. A standalone editor executable
   is insufficient. The shared helper uses `-UsePrecompiled` to compile project
   and plugin modules against those engine binaries; engine object caches are
   not required. `doctor` checks render executables and build tools.
2. An NVIDIA GPU with Vulkan, working drivers, Docker GPU access and NVIDIA
   Container Toolkit. Generation reserves 8 CPUs, 64 GiB RAM and one GPU;
   independent collection uses 12 CPUs and 48 GiB RAM. Allow disk space for the
   original engine, two copies, build caches, outputs and offline libraries.
3. A Codex 0.163.0 native CLI and the L3 agent image. After building
   `3dbench-codex:0.163.0` in the installation section:

```bash
npm install --prefix /absolute/path/to/l3-cli @openai/codex@0.163.0
docker build -t 3dbench-l3-agent:ue5.8.3-codex0.163.0 \
  --build-arg AGENT_UID="$(id -u)" --build-arg AGENT_GID="$(id -g)" \
  -f harness/L3/release/codebase/ue5/agent_environment/Dockerfile \
  harness/L3/release/codebase/ue5/agent_environment

# Test actual container GPU access before copying the engines.
docker run --rm --network none --gpus device=0 \
  3dbench-l3-agent:ue5.8.3-codex0.163.0 nvidia-smi

cp -a --reflink=auto /absolute/path/to/original-engine /absolute/path/to/candidate-engine
cp -a --reflink=auto /absolute/path/to/original-engine /absolute/path/to/evaluator-engine
```

If you have only the licensed source tree, build it before making the copies.
Acquire the matching Epic source revision/archive using your own Epic access;
the repository does not distribute UE. Check the version and source identity
against `engine-lock.json`, then run from that external source tree:

```bash
# Run in the external UE source directory, not the benchmark checkout.
./Setup.sh -exclude=Win32 -exclude=Win64 -exclude=Mac -exclude=Android -exclude=IOS -exclude=TVOS
./GenerateProjectFiles.sh
make -j12 ShaderCompileWorker UnrealEditor UnrealPak
```

Source-engine compilation needs additional disk and RAM. Retain the downloaded
Linux SDK and development headers/libraries. If the engine was built by another
account, ensure every required file is readable and create copies owned by the
account that runs this benchmark. The copies must be writable throughout their
build/cache directories, and must not be mounted by another active run.

Add these values to the main `.env`, using paths on your own host:

```dotenv
L3_UE_ROOT=/absolute/path/to/original-engine
L3_CANDIDATE_ENGINE=/absolute/path/to/candidate-engine
L3_EVALUATOR_ENGINE=/absolute/path/to/evaluator-engine
L3_NATIVE_CLI=/absolute/path/to/l3-cli/node_modules
L3_ASSET_ROOT=/absolute/path/to/offline-l3-assets
L3_UE_IMAGE=3dbench-l3-agent:ue5.8.3-codex0.163.0
L3_GPU=0
```

Paths in `.env` resolve relative to that file; `~` is supported. Command-line
`--l3-engine`, `--l3-evaluator-engine` and `--gpu` override these values.
L3 generation reuses `OPENAI_BASE_URL`/`OPENAI_API_KEY`; judging reuses
`VLM_BASE_URL`/`VLM_API_KEY`, with `gpt-6-astra/medium` fixed by the scoring
protocol. The CLI creates mode-0600 provider JSON files under the ignored
campaign `.private/l3/` directory, outside candidate container mounts. Keys are
never written into reports or campaign identity files. Advanced deployments can
instead set `L3_PROVIDER_DIR` (containing `openai.json`) and
`L3_MATRIX_JUDGE_PROVIDER`; each private JSON uses `base_url` and `api_key`.

Prepare the frozen libraries and check the host through the same public CLI:

```bash
python -m benchmark assets locks
python -m benchmark assets fetch
python -m benchmark assets verify
python -m benchmark doctor --level 3 --verify-assets
```

`fetch` extracts the bundled Kenney CC0 archives and downloads locked Poly Haven
textures. It verifies the pinned URLs and SHA-256 values and resumes verified
files; it does not refresh the catalog. The three libraries are
`kenney-voxel-1.0-tiles`, `kenney-suite-20261023` and `polyhaven-2k-2026-10-16`,
about 35.2 GiB in total. Use `--root PATH` to override `L3_ASSET_ROOT` for an asset
command. The asset download is unnecessary for `doctor --resources-only`.

Run one L3 task, or all 15, exactly as for L1/L2:

```bash
python -m benchmark run \
  --task L3/Image2Environment/task_L3_Image2Environment_005 --output runs/my-model-minecraft
python -m benchmark run --all --level 3 --output runs/my-model-l3

# Optional separate stages; initialization is automatic.
python -m benchmark generate --all --level 3 --output runs/my-model-l3-staged
python -m benchmark evaluate --all --level 3 --output runs/my-model-l3-staged --resume
python -m benchmark export --output runs/my-model-l3-staged
```

Generation includes development builds and preview renders. Evaluation rebuilds
the frozen source independently, renders new views and interaction episodes,
then computes geometry/interaction measurements and calls the visual judge.
These stages do not require a separate render command. The first Vulkan run
compiles shaders into the fresh workspace cache and can spend several minutes
before the first PNG; follow the retained `editor.log` for progress. A successful model/API
response alone does not establish that compilation, rendering or scoring passed.

L3 retains native projects and evidence under `OUTPUT/l3/`. Accepted source is
frozen and validated before scoring and on resume. Completed scores are reused
only after source and report hash checks. A completed collection can be reused
after source, verifier-project and captured-evidence hash checks when scoring
fails. Incomplete collection evidence is retained before a fresh retry. Native `score_100` is normalized to `S_core=score_100/100`
in the shared `main_results/` and `scores.csv`, and included in the same
`leaderboard.csv` and `weighted-summary.json`. Use a fresh output directory when
changing model, GPU, engine paths or L3 runtime bindings.
L3 retains its native delivery/continuation policy. The Blender-specific
`--attempts` and stage timeout flags apply to L1/L2; they do not impose a new
wall-clock limit on native UE continuations.

The unified CLI and offline orchestration are regression-tested. Supply the
licensed engine and host paths above for a complete host test; resource preflight
makes no model calls and does not launch UE. The [runtime prerequisites](README.md#requirements)
explain the online validation boundary. Harbor integration details remain in the
[L3 implementation notes](../harness/L3/release/README.md).

## Generate and evaluate one task

```bash
python -m benchmark run \
  --task L1/Text2Code/task_L1_Text2Code_001 \
  --output runs/my-model-text001
```

The tested model defaults to OPENAI_MODEL; --model MODEL_ID overrides it.
The first source bundle passing public execution/delivery validation is fixed.
Evaluation executes fresh seeds, inspects native geometry, checks saved-scene
renders and exports where required, runs frozen visual/detail judges, and
writes a final report.

The same interface covers extension and real-photo tasks:

```bash
python -m benchmark run \
  --task L1/Image2Code/task_L1_Image2Code_017 \
  --output runs/my-model-image017

python -m benchmark run \
  --task L2/Reference2Scene-RealPhoto/task_L2_Reference2Scene-RealPhoto_009 \
  --output runs/my-model-photo009
```

The lower-level python -m orchestrator entry point remains for native-harness
diagnostics. Use python -m benchmark for complete public scoring.

## Run the full collection

`--all` selects all **145 tasks in this checkout** (65 L1, 65 L2 and 15 L3).
Complete both Blender and UE setup above before an unfiltered full run.
The batch CLI dispatches one task at a time; it has no concurrent-worker flag.
The full dispatch, filtering, failure continuation and resume paths have offline
regression coverage; this is separate from running every task with real models.

```bash
python -m benchmark doctor
python -m benchmark run --all --output runs/my-model-contract
```

To finish all generation before any judging:

```bash
python -m benchmark generate --all --output runs/my-model-contract
python -m benchmark evaluate --all --output runs/my-model-contract --resume
```

Tasks are processed sequentially, keeping ownership and resource usage explicit.
Filter with `--level 1`, `--level 2`, `--level 3`, `--level 1 2` (Blender only),
or `--category Reference2Scene-RealPhoto`.
Repeat --task for a task set. Use a separate directory per model/effort.

For an L1-only campaign, for example:

```bash
python -m benchmark run --all --level 1 --output runs/my-model-l1
```

A task exception is recorded in `benchmark.json`; subsequent tasks continue,
and the command returns 2 if any task failed. Inspect retained evidence before
using the same command with `--resume`. Completed source/report caches are
hash-checked and reused. Configuration changes require a new output directory.
`summary.json` contains the diagnostic mean across completed normalized scores.
The release total is produced automatically once all 145 scores are present.
For separate campaigns, combine their CSV files with `benchmark summarize`.

L1/L2 uses one [released experiment policy](../configs/release/experiment-policy.json):
**model-contract effort (Qwen xhigh, Gemini high, otherwise max); at most six harness attempts (five retries); 16 hours per
model invocation; 32 hours total generation per task**, including retries,
backoff and public delivery validation. The total budget takes precedence over
the attempt count. Internal generator retries are disabled so they do not
multiply the six harness attempts. Blender execution defaults to 8 hours per
process; evaluation has a separate 24-hour native-stage budget.

`--generation-timeout`, `--generation-total-timeout`, `--execution-timeout` and
`--evaluation-timeout` can lower the limits for diagnostic runs. Raising them
above the released caps is rejected. Smaller-budget diagnostic runs must be
reported separately. Campaigns bind these settings; resume retains consumed
generation time and cannot silently adopt a different policy. Extension
assessment still uses stage budgets; its evaluation timeout is not a global
wall-clock guarantee. See [experiment settings](en/experiment.md).
The full collection requires substantial model/rendering resources.
Failed model generations are never replaced by fixed fixtures.

## Resume and inspect

```bash
python -m benchmark run --all --output runs/my-model-contract --resume
```

A campaign lock prevents two writers from sharing one output directory.
Resume verifies accepted source hashes and reuses retained stages. It never
regenerates an accepted answer to improve its score. Failed/partial evidence
is retained; missing measurements are not replaced with invented zeros.
Inspect failed attempts before requesting further calls.

```text
runs/my-model-contract/
  campaign.json               # model/effort and judge settings
  contracts/                  # relocated frozen rules, no old results
  benchmark.json              # task state and failures
  jobs/<task>/generation/     # responses and accepted source
  jobs/<task>/native/         # execution, seeds and evidence
  main_results/<model>/<task>/report.json
  scores.csv                  # final finite scores only
  summary.json                # completed count and mean
```

L3 uses the same final report/CSV paths, with these additional directories:

```text
OUTPUT/l3/runs/<task-key>/<model>--max/workspace/project/  # editable UE project
OUTPUT/l3/runs/<task-key>/<model>--max/workspace/checks/   # development builds/previews
OUTPUT/l3/evaluations/fresh/<task-key>--<model>--max/
  runtime/<task-key>/             # independent build, images and interaction evidence
  review-v5/<task-key>/<model>/summary.json
  verifier-result.json           # final measured status and bound report SHA-256
```

Suite renders are under `runtime/<task-key>/workspace/episodes/`; Minecraft
uses `runtime/<task-key>/verification/` and its image manifests. Retain the
runtime logs and manifests when diagnosing an absent PNG or incomplete score.
To accept a run, check `benchmark.json` task status, the final report's
`score_valid`, and its evidence paths. An incomplete run returns nonzero and
must not be presented as a completed measurement.

Extension task evidence also lives in each job's addition-evaluation directory.
Reports retain components, weights, hashes, judge identity, coverage, missingness
and evidence paths. S_core is in [0,1]. Average within the same task set/effort;
keep incomplete coverage and different efforts visible.

## Validate

```bash
python -m benchmark doctor --resources-only
python scripts/verify_release.py
python -m pytest

# Focused offline batch/resume dry-run (generation/judging use test doubles):
python -m pytest tests/test_batch_cli.py tests/test_campaign_recovery.py -q

# Independent L3 implementation regressions (no UE/model requests):
(cd harness/L3/release/codebase && python -m pytest tests/l3 --noconftest -q)

# No paid API calls: synthetic geometry, real Docker/Blender render/export.
python scripts/smoke_offline.py --blender "$THREEDBENCH_BLENDER" \
  --output /tmp/3dbench-offline-smoke

# Source fixture; not a model result. Visual/detail scoring still calls a judge.
python -m benchmark run \
  --task L1/Text2Code/task_L1_Text2Code_001 \
  --submission examples/flange-source --model fixture-only \
  --output runs/fixture-text001 --effort max
```

Use --runtime local only for trusted source; it runs with host permissions.
Docker candidate execution is the default. See [SECURITY](../SECURITY.md).
See [runtime prerequisites](README.md#requirements) for validation scope.
The offline smoke creates a synthetic scene and verifies Blender render/export.
Online generation, judge scoring and UE deployment have separate validation evidence.

## Aggregate L1/L2/L3 scores

After generation and item evaluation, combine normalized CSV results:

```sh
python -m benchmark summarize --scores /path/to/l1-l2/scores.csv \
  --scores /path/to/l3/scores.csv --output runs/combined
```

L3 Harbor keys are mapped to the continuous release IDs. Use `--identity source`
only when importing an older L1/L2 CSV with the original task identities; old
and new numeric IDs can collide and must not be inferred automatically. Exported
`leaderboard.csv` and `weighted-summary.json` include normalized L1/L2/L3 scores,
weighted contributions, total and coverage. A level is published only with its
complete task population; total requires all 145 tasks. `summary.json/mean` from
a partial L1/L2 campaign remains an unweighted diagnostic, not the release total.
See [aggregation and numbering](en/tasks.md) and the [complete experiment contract](en/experiment.md) for the frozen policy.
