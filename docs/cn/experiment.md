# 实验设置

[English](../en/experiment.md) · [文档导航](README.md)

生成与测评统一使用[主CLI](../../README.md#generate-and-evaluate-one-task)。先选择[模型与执行器](models.md)，配置生成和裁判服务，以单题检查环境后再扩大到全量campaign。

## L1/L2预算与重试

[运行策略](../../configs/release/experiment-policy.json)规定：

| 设置 | 上限 |
| --- | --- |
| 生成effort | 模型表：Qwen xhigh、Gemini high，其余已列模型max |
| harness总尝试数 | 最多6次：初次加最多5次重试 |
| 每次尝试内的generator调用 | 1次 |
| 单次生成调用 | 57,600秒／16小时 |
| 单题生成总预算 | 115,200秒／32小时 |
| 单次Blender执行 | 28,800秒／8小时 |
| 原生测评阶段 | 86,400秒／24小时 |

生成、退避、公开执行和交付验证共享32小时预算，每次调用还受剩余预算约束。首次有效交付即停止重试，6次尝试不产生96小时额度。`GENERATOR_MAX_ATTEMPTS=1`关闭内层重试，`--attempts=6`设置外层上限。传输错误、超时或公开交付失败可触发重试；候选修复只接收公开执行反馈，不接收测评分数。

生成与测评分开计时。24小时限制用于原生阶段，扩展、detail、重渲染及裁判阶段仍有各自时限，尚未形成覆盖完整测评链路的统一墙钟退出保证。部分裁判适配器也设置独立timeout和轮数上限。诊断可缩短预算，结果需注明实际设置；公开CLI拒绝超过发布策略的上限。

## L3流程

L3使用相同的`python -m benchmark`入口，内部遵循单独的完整交付流程。3,600秒是目标时长，不是生成硬超时；继续运行循环不继承L1/L2的6次尝试上限。Harbor题包分别声明24小时agent、24小时verifier和1小时环境构建上限，记录时分别注明。候选生成与独立测评使用各自可写的UE引擎副本，配置见[L3安装说明](../../README.md#configure-l3-ue)。

## 恢复运行

~~~sh
python -m benchmark run --all --output runs/my-model-contract --resume
~~~

campaign绑定模型、effort、harness、题目输入、策略、已接受源码及配置哈希。更改这些内容需使用新输出目录。运行锁阻止并发写入。已接受源码校验后复用，未完成阶段保留日志和证据。

`jobs/<task>/generation/generation-budget.json`持久保存已消耗的生成时间，恢复使用剩余额度和已有尝试历史。进程意外结束后，未结算区间按已过去的墙钟时间保守计入；重启不会重置预算。

不同模型／effort使用不同输出目录。状态、证据、用量与导出见[结果说明](results.md)。

## 配置文件

| 定义 | 文件 |
| --- | --- |
| 模型、执行器与effort | [model-harness-contract.json](../../configs/release/model-harness-contract.json) |
| CLI包和版本 | [generator-harnesses.json](../../configs/release/generator-harnesses.json) |
| 生成与执行上限 | [experiment-policy.json](../../configs/release/experiment-policy.json) |
| 题目身份 | [task-id-map.json](../../configs/release/task-id-map.json) |
| 层级均分与总分 | [aggregation-policy.json](../../configs/release/aggregation-policy.json) |
| L1/L2评分 | [scoring-task-inventory.json](../reference/scoring-task-inventory.json) |
| L3评分 | [scoring-specs](../../harness/L3/release/scoring-specs/manifest.json) |

独立裁判保持`gpt-6-astra/medium`。题内权重见[评分规则](scoring.md)，层级30/30/40汇总见[题目与汇总](tasks.md)。
