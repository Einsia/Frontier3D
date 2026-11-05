# Text2Code 001 测评接入

题内入口提供原生测量，具体覆盖按配置逐项列出。`eval_spec.json` 的 18 条要求固定保留，完整/部分/缺失状态和原因逐项列出。未覆盖要求使 `case_pass=false`，`S_diagnostic` 仅为现有方法的诊断分。

仅使用本题法兰总成参数，不沿用旧联轴器规格。已接入名称无关的尺寸清单、11 件计数、闭合/连通/有效实体、两帧诊断视图、GLB/README 可读取及 seed 重现证据。尺寸代理不证明孔洞或角色；诊断相机仍有整体位移限制。孔道、装配/间隙、角色材质、完整状态语义及正式标定仍未完成。

题内入口只检查产物，不启动生成器或重试。完整运行从项目根目录使用：

```bash
.venv/bin/python -m orchestrator run --task L1/Text2Code/task_L1_Text2Code_001 --submission /absolute/path/to/source
```

默认使用 Docker，独立基准和 seeds 0/1/2 都从同一份冻结源码的清洁副本生成，调用共享重现/评分方法，结果写到 `data/task_runs`。将 `--submission` 换成 `--generate` 使用外部生成器。模型仅接收题面及 manifest 白名单输入；私有 `solution/` 不挂载。

已有产物可单独检查（需要项目 Python 环境）：

```bash
.venv/bin/python data/3dbench/tasks/L1/Text2Code/task_L1_Text2Code_001/harness/evaluate.py --submission /absolute/path/to/output --blender third_party/blender-5.2.1-linux-x64/blender
```

独立检查不会认可候选自报的执行记录；没有 orchestrator 实际执行证据时执行门不可通过。`mvp` 表示允许调用此入口，不表示模型成功或全部要求已实现。

## 评分

本题最终得分：`60% vlm + 30% data + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
