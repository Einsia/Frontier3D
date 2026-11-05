# 流鬃马头雕像

单视图静态对象重建，难度 medium（设计预估）。重建马头雕像及矩形底座。保留长额头和口鼻、两只竖耳及耳内凹陷、可见眼睛与鼻孔、下颌，以及颈部向胸部延伸的连续弧面。后掠的主要鬃毛束要有层叠曲面体积和清楚的沟槽，不能只画几条色带。颈部落在底座上，保持青铜质感；细小划痕与细发丝可以简化。

| 项目 | 内容 |
|---|---|
| 模型可见输入 | instruction.md；environment/input/reference.png（仅这一张图） 与 CREDIT.txt |
| 固定输出 | output/solution.py、scene.blend、scene.glb、main.png（1000×1000）、README.md；可选 assets/ |
| 评测私有资料 | solution/reference/ 原生 GT、GLB、四视图及 audit.json；solution/provenance/ 来源许可；solution/EVALUATION.md 指标和读取方式 |
| 中文筛选稿 | instruction.zh.md，与英文要求等价，不作为额外模型输入 |
| harness | 通过仓库公共入口调用逐题原生或扩展测评；最终权重见评分说明 |

入口命令与可移植要求见 [英文 instruction](instruction.md)。最大跨度统一为 1 m，静态第 1 帧，无爆炸图要求。未给模型的其他视角不作为隐藏表面精确评分目标。详细指标见 [评测说明](solution/EVALUATION.md)。

![模型主参考图](environment/input/reference.png)

来源：[Tina](https://polyhaven.com/a/horse_head)，CC0-1.0。Static evaluated geometry; uniform normalization to 1 m maximum span; new studio cameras and lighting.
