# Tasks and aggregation

[中文](../cn/tasks.md) · [Documentation](../README.md)

The release contains **145 tasks: 65 L1, 65 L2 and 15 L3**. Packages are in
[data/3dbench/tasks](../../data/3dbench/tasks); global IDs run from `3DBench-001`
to `3DBench-145`. L1/L2 has 84 native-harness tasks and 46 extension tasks.

| Level | Category | Tasks |
| --- | --- | ---: |
| L1 | Text2Code | 15 |
| L1 | Image2Code | 25 |
| L1 | Image2Code-SingleView | 25 |
| L2 | Brief2Scene | 20 |
| L2 | Reference2Scene | 10 |
| L2 | Reference2Scene-RealPhoto | 25 |
| L2 | SceneEdit | 10 |
| L3 | Text2Environment | 5 |
| L3 | Image2Environment | 10 |

All levels use the same public CLI:

~~~sh
python -m benchmark list
python -m benchmark run --task L1/Text2Code/task_L1_Text2Code_001 --output runs/check-l1
python -m benchmark run --task L3/Image2Environment/task_L3_Image2Environment_001 --output runs/check-l3
~~~

## L3 identities

L3 directories follow public `references.json/input_mode`: five text tasks and
ten image tasks, with 24 public reference images. The separate frozen scoring
reference set has 23 bindings. Directory IDs are `Text2Environment_001`–`005`
and `Image2Environment_001`–`010`; global IDs 131–145 retain native `l3-e/g/r`
keys. The runner accepts the public IDs and native keys.

[task-id-map.json](../../configs/release/task-id-map.json) records source IDs.
The [L3 alias map](../../configs/release/l3-input-category-map.json) explicitly
resolves former Unified IDs. Numeric suffixes alone cannot identify an old task.
CodeEdit and PlayableGame packages are excluded from the active release.

## Aggregate scores

L1/L2 uses `100 * S_core`; L3 uses `score_100`. Each level is the arithmetic
mean of all its tasks, then:

~~~text
Total = 0.30 * L1 + 0.30 * L2 + 0.40 * L3
~~~

| Level | Required scores | Total weight | Contribution per task |
| --- | ---: | ---: | ---: |
| L1 | 65 | 30% | 0.461538% |
| L2 | 65 | 30% | 0.461538% |
| L3 | 15 | 40% | 2.666667% |

Tasks have equal weight within a level. A complete level requires every task;
the total requires all 145. Missing and technical-invalid measurements stay
missing. Valid measured zeros count. Weights are never redistributed for
missing tasks. Scores are grouped by model **and effort**.

~~~sh
python -m benchmark summarize --scores /path/to/l12/scores.csv --scores /path/to/l3/scores.csv --output runs/combined
~~~

This writes `leaderboard.csv` and `weighted-summary.json`, including coverage,
level means and weighted contributions. For CSV files with source-era IDs,
filter retired tasks and explicitly use `--identity source`. Create a fresh
campaign when changing its bound task release.

Machine definitions: [aggregation policy](../../configs/release/aggregation-policy.json),
[task collection](../../data/3dbench/tasks/collection.json), [task table](../reference/task-index.csv).
