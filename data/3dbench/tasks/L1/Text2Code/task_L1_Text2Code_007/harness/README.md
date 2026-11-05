# Text2Code 007：滑动门闩总成

任务 ID：`L1/Text2Code/task_L1_Text2Code_007`。题内只保留独立评分规格、覆盖说明和评分入口；生成、容器、超时、重试及清洁重跑由项目外部 `orchestrator/` 负责，取证算法复用 `src/evaluator/`。

当前 manifest：`mvp`。已启用逐题评分；实际运行状态与证据见[公开评分覆盖说明](../../../../../../../docs/en/scoring.md#validity-and-partial-credit)。原生入口启用状态不代表完整语义验收。

共 19 条要求：完整 3、部分 14、缺失 2。所有必需要求保留在固定分母，诊断高分不能使未覆盖要求通过。

按公开题面配置本题零件/尺寸清单、闭合/连通/有效实体、帧 1/61 审阅图、GLB 和 README；原生重现序列为 1→61→1，GLB 只比较装配态。尺寸及位置容差为 0.3 mm。

孔位取证使用本题实际几何的多截面及轴向采样。孔径容差先折半为半径容差；它仍是有限采样，不证明连续孔道、所有加工特征或装配关系。 固定审阅视图只作非空诊断，不将自由相机或合法爆炸布局当隐藏目标。

- 已接入完整检查：闭合/连通、有效实体、GLB 可读。
- 部分要求：`part_roles`、`plate`、`blocks`、`sliding_bolt`、`handle`、`grip`、`stop_rings`、`fasteners`、`units`、`hierarchy`、`state_cycle`、`glb_assembled`、`reconstruction`、`instructions`。
- 尚未接入：`assembly_clearance`、`materials`。

每条要求的具体含义、测量检查和缺口原因见 `eval_spec.json` 的 `l1_protocol.requirements`。

从项目根目录通过 `.venv/bin/python -m orchestrator run --task L1/Text2Code/task_L1_Text2Code_007 --submission <候选源码目录>` 运行。原生、GLB、全部 seed、核心/诊断分、失败或不可测原因保存在 `data/task_runs`。公开题面编写的测试候选不计为模型成绩。

## 评分

本题最终得分：`60% vlm + 30% data + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
