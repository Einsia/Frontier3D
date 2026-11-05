# Brief2Scene：俯视卡通工地

按文字设计约 40×30 m、可用于俯视经营游戏的卡通工地。

| 项目 | 内容 |
| --- | --- |
| 模型输入 | 仅英文 instruction；无参考图、初始模型或额外规格文件。 |
| 模型输出 | `output/solution.py`、`output/scene.blend`、`output/main.png`、`output/alternate.png`、`output/README.md`；细节见 instruction。 |
| 评测参考 | 工地原模型和渲染仅为设计示例；没有唯一正确布局，不做真值像素/几何匹配。 |

[English instruction](instruction.md) · [中文筛选版](instruction.zh.md) · [详细评测指标](solution/EVALUATION.md)

| 核心指标 | 检查内容 |
| --- | --- |
| 内容覆盖 | 建筑、塔吊、两类车辆、堆料区、道路、围挡和入口。 |
| 交通与净空 | 入口到作业区连通，道路净宽 ≥ 4 m，材料不堵路。 |
| 空间合理性 | 场地规模、比例、支撑与无不合理穿透。 |
| 画面与复现 | 卡通风格、俯视分区可读性、双视图与同种子一致性。 |

运行/加载成功率和时间、token、工具/渲染调用成本作为公共指标。

模型只接收 `instruction.md` 与 `environment/` 的内容（保留 `input/` 相对路径）；不开放整个 task 目录。`harness/` 只有 Git 占位文件，暂不实现 `declaration.py`。
