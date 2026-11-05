# 密封电子盒总成

依据文字尺寸建立 15 件可编辑装配，考察孔轴配合、零件间位置关系与装配/爆炸双状态。全部规格在 instruction 中，无结构化规格输入。

| 模型输入 | 固定交付 | 私有参考 |
|---|---|---|
| 英文 instruction；environment/input 为空 | output/solution.py、scene.blend、scene.glb、README.md | 完整模型、四张评审图、解析规格、占据探针、零件检查与改动记录 |

只向模型提供 instruction.md 和 environment；中文 instruction.zh.md 供筛选。solution 不挂载给模型；生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。来源为已有原创 CC0 候选，提供参考总成，资产加工说明见 provenance。参考图不提供给模型。

![私有装配参考](solution/reference/assembled.png)

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)
