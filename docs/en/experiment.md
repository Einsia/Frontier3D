# Experiment settings

[中文](../cn/experiment.md) · [Documentation](../README.md)

Use the [main CLI](../installation.md#generate-and-evaluate-one-task) for generation and evaluation. Choose a [model and harness](models.md), configure generation and judge providers, and start with one task before a full campaign.

## L1/L2 budgets and retries

The [runtime policy](../../configs/release/experiment-policy.json) defines:

| Setting | Limit |
| --- | --- |
| Generation effort | Model contract: Qwen xhigh, Gemini high, other listed models max |
| Harness attempts | At most 6 total: initial attempt plus up to 5 retries |
| Generator invocations per attempt | 1 |
| One generation invocation | 57,600 seconds / 16 hours |
| Total generation per task | 115,200 seconds / 32 hours |
| One Blender execution | 28,800 seconds / 8 hours |
| Native evaluation phase | 86,400 seconds / 24 hours |

Generation, backoff, public execution and delivery validation share the 32-hour budget. Each invocation is limited by the remaining budget. The first accepted delivery stops retries. Six attempts do not create a 96-hour allowance. `GENERATOR_MAX_ATTEMPTS=1` disables inner retries; `--attempts=6` sets the outer limit. Transport errors, timeouts and public delivery failures can trigger retries. Candidate repair receives public execution feedback, without evaluation scores.

Generation and evaluation have separate clocks. The 24-hour setting constrains the native phase; extension, detail, rerendering and judge stages retain their own deadlines. It is not a global wall-clock deadline for the complete evaluation pipeline. Some judge adapters set their own timeouts and round limits. Record shorter diagnostic budgets with the results; the public CLI rejects limits above the release policy.

## L3 workflow

L3 uses the same `python -m benchmark` entry point and a separate native complete-delivery workflow. Its 3,600-second target is not a hard generation timeout. The continuation loop does not inherit the L1/L2 six-attempt limit. Harbor task packages separately declare 24-hour agent, 24-hour verifier and one-hour environment-build timeouts. Record these separately. Candidate generation and independent measurement use separate writable UE engines; see [L3 setup](../installation.md#configure-l3-ue).

## Resume

~~~sh
python -m benchmark run --all --output runs/my-model-contract --resume
~~~

A campaign binds the model, effort, harness, task inputs, policy, accepted source and configuration hashes. Changing these requires a new output directory. A lock prevents concurrent writers. Accepted source is reused after verification, and incomplete stages retain logs and evidence.

`jobs/<task>/generation/generation-budget.json` persists elapsed generation time. Resume uses the remaining budget and existing attempt history. After an abrupt termination, the unfinished interval is conservatively counted as elapsed wall-clock time. Restarting does not reset the budget.

Use separate output directories for different model/effort combinations. [Results](results.md) describes states, evidence, usage and exports.

## Configuration files

| Definition | File |
| --- | --- |
| Models, harnesses and effort | [model-harness-contract.json](../../configs/release/model-harness-contract.json) |
| CLI packages and versions | [generator-harnesses.json](../../configs/release/generator-harnesses.json) |
| Generation and execution limits | [experiment-policy.json](../../configs/release/experiment-policy.json) |
| Task identity | [task-id-map.json](../../configs/release/task-id-map.json) |
| Level means and total | [aggregation-policy.json](../../configs/release/aggregation-policy.json) |
| L1/L2 scoring | [scoring-task-inventory.json](../reference/scoring-task-inventory.json) |
| L3 scoring | [scoring-specs](../../harness/L3/release/scoring-specs/manifest.json) |

The judge remains `gpt-6-astra/medium`. See [scoring](scoring.md) for item weights and [tasks](tasks.md) for 30/30/40 level aggregation.
