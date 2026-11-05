# 八角飞檐宫灯

多视图静态对象重建，难度 medium（设计预估）。重建完整八角宫灯。保留八边木框、凹入的浅色面板、同心多边形顶部框架和抬高的中央顶盖、向外上翘的角部饰件、向下弯曲的脚部，以及悬绳、串珠和红色流苏。重复构件围绕八面均匀布置，同时匹配可见比例与遮挡。弯曲木饰、框架进深和流苏体积需要真实几何。面板画可简化成配色与位置相近的疏落花枝，不要求精确笔触。本题为未点亮的展示物，不要求电路或发光机构。

| 项目 | 内容 |
|---|---|
| 模型可见输入 | instruction.md；environment/input/reference.png、front.png、side.png、top.png 与 CREDIT.txt |
| 固定输出 | output/solution.py、scene.blend、scene.glb、main.png（1000×1000）、README.md；可选 assets/ |
| 评测私有资料 | solution/reference/ 原生 GT、GLB、四视图及 audit.json；solution/provenance/ 来源许可；solution/EVALUATION.md 指标和读取方式 |
| 中文筛选稿 | instruction.zh.md，与英文要求等价，不作为额外模型输入 |
| harness | 通过仓库公共入口调用逐题原生或扩展测评；最终权重见评分说明 |

入口命令与可移植要求见 [英文 instruction](instruction.md)。最大跨度统一为 1 m，静态第 1 帧，无爆炸图要求。评测覆盖四个公开视角可见表面的并集。详细指标见 [评测说明](solution/EVALUATION.md)。

![模型主参考图](environment/input/reference.png)

来源：[Kirill Sannikov](https://polyhaven.com/a/chinese_chandelier)，CC0-1.0。Static evaluated geometry; uniform normalization to 1 m maximum span; new studio cameras and lighting.
