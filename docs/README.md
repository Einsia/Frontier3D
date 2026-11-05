# Documentation

[中文](cn/README.md)

Start with [installation and running](installation.md) for setup and the unified
`python -m benchmark` commands for generation, rendering and evaluation.
The [repository README](../README.md) introduces the benchmark and its citation.
English is the default; the core guides have matching Chinese editions.

| Guide | English | 中文 |
| --- | --- | --- |
| Tasks and aggregation | [Tasks](en/tasks.md) | [题目与汇总](cn/tasks.md) |
| Models and harnesses | [Models](en/models.md) | [模型配置](cn/models.md) |
| Budgets, retries and resume | [Experiments](en/experiment.md) | [实验设置](cn/experiment.md) |
| Scoring and partial credit | [Scoring](en/scoring.md) | [评分规则](cn/scoring.md) |
| Output files and score export | [Results](en/results.md) | [结果与导出](cn/results.md) |
| Task asset licenses | [Licenses](en/licenses.md) | [资产许可](cn/licenses.md) |

Detailed [metric formulas](en/reference/metrics.md) and [L3 UE scoring](en/reference/l3.md)
are English reference pages. Machine-readable task, scoring and attribution
indexes are grouped in [reference/](reference/README.md).

## Requirements

| Scope | Requirements |
| --- | --- |
| All levels | Linux x86-64, Python 3.13, Node.js 22+, Git LFS, Docker and the selected model CLI/provider |
| L1/L2 | Blender 5.2.1 and the candidate-execution Docker image |
| L3 | Licensed UE 5.8.3, separate writable candidate/evaluator engines, NVIDIA/Vulkan, an external CLI prefix and verified asset libraries |

The [installation guide](installation.md#install) and [L3 setup](installation.md#configure-l3-ue)
provide the commands. API requirements vary by [harness](en/models.md). Use Docker
for untrusted candidates; local execution uses host permissions. See [Security](../SECURITY.md).

## Check your installation

~~~sh
python -m benchmark doctor --resources-only
python scripts/verify_release.py
python -m benchmark doctor
~~~

The resource check needs no model service. Configured doctor checks executables,
versions and host settings without model calls or UE launches. Confirm provider
and GPU availability with an actual task before starting `run --all`. Offline
tests check implementation behavior; they do not establish successful online
generation and evaluation of all 145 tasks on every provider and host.
