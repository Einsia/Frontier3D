# 结果与导出

[English](../en/results.md) · [文档导航](README.md)

先查看`benchmark.json`中的题目状态，再读取最终报告及其证据路径。完整成绩要求必需测量齐全，且源码和报告绑定有效。

## 输出文件

~~~text
OUTPUT/
  campaign.json                         # 模型、effort、裁判与策略
  benchmark.json                        # 各题状态与失败
  contracts/                            # 运行时评分规则
  jobs/<task>/generation/               # 响应、尝试和接受源码
  jobs/<task>/native/                   # 原生执行及seed证据
  jobs/<task>/addition-evaluation/      # 扩展题测量
  main_results/<model>/<task>/report.json
  scores.csv
  summary.json
  leaderboard.csv
  weighted-summary.json
~~~

原生L1/L2还使用输出目录内的`legacy_baseline/`、`legacy_detail/`和`legacy_v2/`保存当前测量阶段的产物，具体路径按报告指针读取。

L3使用相同的最终报告／CSV路径，另有：

~~~text
OUTPUT/l3/runs/<task-key>/<model>--<effort>/workspace/
  project/                             # 候选UE源码
  checks/                              # 开发构建和预览
OUTPUT/l3/evaluations/fresh/<task-key>--<model>--<effort>/
  runtime/<task-key>/                   # 独立构建、图像与回放
  review-v5/<task-key>/<model>/summary.json
  verifier-result.json
~~~

Suite图片位于`runtime/<task-key>/workspace/episodes/`，Minecraft使用`runtime/<task-key>/verification/`及图片清单。候选开发预览本身不能证明独立测评完成。

## 成绩报告

| 字段 | 含义 |
| --- | --- |
| `task_id`、`model`、effort | 题目与被测模型身份 |
| `S_core` | `[0,1]`最终成绩，`null`表示测量不完整 |
| `status`、`score_valid`、gates | 测量和交付状态 |
| `scoring_version`、`method_version` | 实际组合与测量版本 |
| `components`／`score_components`、`component_weights` | 分项值与可用最终系数 |
| `missing_components`、`missing_measurements` | 未完成的必需测量 |
| `source_bindings`、`artifact_sha256` | 源码、规则、采集器和产物哈希 |
| `judge_model`、`judge_effort` | 独立裁判身份 |
| `required_variants`、`measured_variants`、`selected_variant` | Detail总体与选中的最小变体 |
| `quality_diagnostics`、`robustness_recovery` | 图片／seed差异及明确政策下的部分分恢复 |
| `formal_score_eligible`、`human_calibrated`、`limitations` | 校准与解释限制 |

部分字段位于关联分项报告。`measurements`可能按路由使用列表或字典。裁判`S_vlm`、原生中间分和screening值各有用途，单题成绩读取最终`S_core`。有效零分、交付失败和技术缺测的区别见[评分规则](scoring.md#有效性与部分分)。

## 导出与汇总

~~~sh
python -m benchmark export --output runs/my-model-contract
python -m benchmark summarize --scores runs/my-model-contract/scores.csv --output runs/combined
~~~

`scores.csv`保存有限最终分数、状态、有效性、effort、报告路径与哈希，缺测／非有限值不导出；无效测量不进入加权总分。`summary.json/mean`是已导出行的无权诊断均分。完整发布总分位于`leaderboard.csv`和`weighted-summary.json`，使用[各层全部题均分](tasks.md#成绩汇总)，模型／effort分别成组。

`--resume`复用前检查已接受源码和缓存报告。定位失败时保留生成、运行和裁判日志。源码或证据哈希不符需查明原因，配置变化时创建新campaign。

## 用量

用量为返回的输入加输出。缓存读／写计数属于输入子集，reasoning输出属于输出子集。修复用量已包含在累计生成用量中。生成与裁判用量分别统计，未知计数保留未知。原生事件、适配器哈希与尝试记录标识选中的交付及失败尝试。

## 裁判配置

默认裁判为`gpt-6-astra/medium`。[compact_judge](../../src/agent_judge/invocation_policy.py)在多条路由中直接指定该身份，其他路径读取配置。单独更改`VLM_MODEL`可能造成调用身份不一致或最终汇总失败；切换裁判需统一修改适配器与校验，并创建新campaign。

部分裁判适配器有固定timeout和轮数，扩展与detail阶段也有独立时限，见[实验设置](experiment.md)。图像区域、二维框、VLM判断及有限几何采样的适用范围见英文[算法参考](../en/reference/metrics.md)。有限总分不会自动消除校准标记，也不能证明全部题目要求均已覆盖。
