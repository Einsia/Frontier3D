# Results and exports

[中文](../cn/results.md) · [Documentation](../README.md)

Start with `benchmark.json` for task state, then read each final report and its evidence paths. A completed score requires the task's measurements and valid source/report bindings.

## Output files

~~~text
OUTPUT/
  campaign.json                         # model, effort, judge and policy
  benchmark.json                        # task states and failures
  contracts/                            # materialized scoring rules
  jobs/<task>/generation/               # responses, attempts and accepted source
  jobs/<task>/native/                   # native execution and seed evidence
  jobs/<task>/addition-evaluation/      # extension measurements
  main_results/<model>/<task>/report.json
  scores.csv
  summary.json
  leaderboard.csv
  weighted-summary.json
~~~

Native L1/L2 measurement stages also use `legacy_baseline/`, `legacy_detail/` and `legacy_v2/` inside the output directory. Follow report pointers for exact paths. These names identify current implementation stages.

L3 uses the same final report/CSV paths and adds:

~~~text
OUTPUT/l3/runs/<task-key>/<model>--<effort>/workspace/
  project/                             # candidate UE source
  checks/                              # development builds and previews
OUTPUT/l3/evaluations/fresh/<task-key>--<model>--<effort>/
  runtime/<task-key>/                   # independent build, images and replays
  review-v5/<task-key>/<model>/summary.json
  verifier-result.json
~~~

Suite images are under `runtime/<task-key>/workspace/episodes/`; Minecraft uses `runtime/<task-key>/verification/` and image manifests. Candidate previews alone do not establish independent evaluation completion.

## Score reports

| Field | Meaning |
| --- | --- |
| `task_id`, `model`, effort | Task and tested-model identity |
| `S_core` | Final score in `[0,1]`; `null` indicates incomplete measurement |
| `status`, `score_valid`, gates | Measurement and delivery status |
| `scoring_version`, `method_version` | Actual combination and measurement versions |
| `components` / `score_components`, `component_weights` | Component values and available final coefficients |
| `missing_components`, `missing_measurements` | Unresolved required measurements |
| `source_bindings`, `artifact_sha256` | Source, rule, collector and artifact hashes |
| `judge_model`, `judge_effort` | Independent judge identity |
| `required_variants`, `measured_variants`, `selected_variant` | Detail population and selected minimum |
| `quality_diagnostics`, `robustness_recovery` | Image/seed differences and documented partial-credit recovery |
| `formal_score_eligible`, `human_calibrated`, `limitations` | Calibration and interpretation limits |

Some fields are in linked component reports. `measurements` may be a list or dictionary depending on the route. Judge `S_vlm`, raw native scores and screening values are intermediate values; use the final `S_core` for item results. See [Scoring](scoring.md#validity-and-partial-credit) to distinguish measured zeros from delivery failure and technical missingness.

## Export and aggregation

~~~sh
python -m benchmark export --output runs/my-model-contract
python -m benchmark summarize --scores runs/my-model-contract/scores.csv --output runs/combined
~~~

`scores.csv` contains finite final report scores, status, validity, effort, report path and hash. Confirmed delivery failures (`system_invalid`, `S_core=0`) remain in exports and count as zero in the fixed task population. Technical failures and missing/nonfinite measurements are omitted and block a complete total. The same eligibility rule applies to CSV export and weighted aggregation. `summary.json/mean` is an unweighted diagnostic over exported rows. The complete release total is in `leaderboard.csv` and `weighted-summary.json`, using [all-task level means](tasks.md#aggregate-scores). Model/effort groups remain separate.

`--resume` verifies accepted sources and cached reports before reusing stages. Keep generation, runtime and judge logs when diagnosing failure. A source or evidence hash mismatch requires investigation; choose a new campaign when changing configuration.

## Usage

Usage is returned input plus output. Cache-read/write counters are input subsets; reasoning output is an output subset. Repair usage is already part of cumulative generation usage. Keep generation and judge usage separate and preserve unknown counters as unknown. Retained native events, adapter hashes and attempt records identify the selected delivery and failed attempts.

## Judge configuration

The default judge is `gpt-6-astra/medium`. [compact_judge](../../src/agent_judge/invocation_policy.py) sets this identity in code for several routes, while other paths read the configured judge. Changing `VLM_MODEL` alone may leave inconsistent calls or cause finalization to fail. Switching judges requires consistent adapter and validation changes plus a new campaign.

Some judge adapters have fixed timeout/round limits. Extension and detail phases also have separate deadlines; see [experiment settings](experiment.md). Image regions, 2D boxes, VLM judgments and finite geometric sampling have limits described in the [metric reference](reference/metrics.md). A finite total does not resolve calibration flags or demonstrate every task requirement.
