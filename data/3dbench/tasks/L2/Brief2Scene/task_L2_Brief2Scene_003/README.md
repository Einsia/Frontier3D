# 双向道路与六户住宅街区

按自然语言设计完整场景，重点是六栋不同住宅、双向车道、连续人行道、接入车道、庭院与街树。

| 模型输入 | 固定输出 | 评测侧私有材料 |
|---|---|---|
| 仅 instruction.md；environment/input 为空 | output/solution.py、scene.blend、main.png、alternate.png、README.md | 授权素材构成的场景示例、真实渲染、原生依赖审计、来源与评测说明 |

示例图不提供给模型，不是唯一答案或已验证的满分 GT。按题面约束评测，不按示例构图、源对象名称、原网格拓扑或贴图逐像素打分。instruction.zh.md 用于中文筛选。生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![私有示例，仅供筛选](solution/reference/main.png)

素材：[Kenney](https://kenney.nl/assets/city-kit-suburban)，CC0-1.0；这一来源家族只用于本题。转换与原创场景布置见 solution/provenance。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)
