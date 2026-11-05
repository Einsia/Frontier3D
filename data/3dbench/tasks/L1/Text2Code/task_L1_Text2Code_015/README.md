# Text2Code：文字重建

仅依据文字尺寸，生成包含 11 个独立零件的双半联轴器装配体。

| 项目 | 内容 |
| --- | --- |
| 模型输入 | 仅英文 instruction；无参考图、初始模型或额外规格文件。 |
| 模型输出 | `output/solution.py`、`output/scene.blend`、`output/scene.glb`、`output/README.md`；细节见 instruction。 |
| 评测参考 | 完整装配体、评审图和几何标注；按相对几何评分，允许自由原点与爆炸布局。 |

[English instruction](instruction.md) · [中文筛选版](instruction.zh.md) · [详细评测指标](solution/EVALUATION.md)

| 核心指标 | 检查内容 |
| --- | --- |
| 尺寸与位置 | 尺寸、孔位和装配位置误差 ≤ 0.3 mm。 |
| 结构关系 | 11 件完整，共轴、120° 孔分布、间距、间隙和螺栓穿孔。 |
| 几何与状态 | 闭合/连通、Chamfer、IoU；装配/爆炸形状保持和导出一致性。 |
| 可编辑性 | 独立零件、装配层级与程序复现。 |

运行/加载成功率和时间、token、工具/渲染调用成本作为公共指标。

模型只接收 `instruction.md` 与 `environment/` 的内容（保留 `input/` 相对路径）；不开放整个 task 目录。`harness/` 只有 Git 占位文件，暂不实现 `declaration.py`。
