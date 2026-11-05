# Text2Code 014：平面曲线矩形扫掠件

任务 ID：`L1/Text2Code/task_L1_Text2Code_014`。题内只保留独立评分规格、覆盖说明和评分入口；生成、容器、超时、重试及清洁重跑由项目外部 `orchestrator/` 负责，取证算法复用 `src/evaluator/`。

原生入口使用 manifest 中的 `mvp` 路由。执行证据与内容质量分别记录，入口启用状态不代表候选满足题目要求。

共 14 条要求：完整 3、部分 7、缺失 4。所有必需要求保留在固定分母，诊断高分不能使未覆盖要求通过。

本题只有一件静态实体，原生/GLB 均只观察帧 1，不要求装配层级或爆炸。尺寸/表面位置容差为 0.15 mm。

真实特征取证尚有缺口；已有尺寸代理不能代替孔道、圆柱/扫掠轮廓、接触或完整表面距离判定。 固定审阅视图只作非空诊断，不将自由相机或合法爆炸布局当隐藏目标。

- 已接入完整检查：闭合/连通、有效实体、GLB 可读。
- 部分要求：`editable_part`、`rectangular_section`、`glb_assembled`、`reconstruction`、`instructions`、`units`、`review_view`。
- 尚未接入：`interpolated_path`、`sweep_transport`、`surface_accuracy`、`materials`。

每条要求的具体含义、测量检查和缺口原因见 `eval_spec.json` 的 `l1_protocol.requirements`。

从项目根目录通过 `.venv/bin/python -m orchestrator run --task L1/Text2Code/task_L1_Text2Code_014 --submission <候选源码目录>` 运行。原生、GLB、全部 seed、核心/诊断分、失败或不可测原因保存在 `data/task_runs`。公开题面编写的测试候选不计为模型成绩。

## 评分

本题最终得分：`60% vlm + 30% data + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
