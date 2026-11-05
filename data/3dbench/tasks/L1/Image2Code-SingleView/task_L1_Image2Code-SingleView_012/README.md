# 花纹浮雕宝箱

单视图静态对象重建，难度 hard（设计预估）。重建图中闭合的木宝箱。保留矩形下箱体、连续拱起的箱盖、盖体接缝、金属包边与箍带、凸起花纹金属片、中央锁扣，以及可见侧把手及连接座。金属饰片应高于木面，有可读厚度及主要镂空或凹陷，不能将全部装饰替换为平面照片。匹配主要木材、暗色金属及可见箍带花纹的重复关系。细木纹、划痕和细刻线可简化。箱盖与下箱体应能作为不同部件编辑，但不要求开盖动画或不可见的箱内结构。

| 项目 | 内容 |
|---|---|
| 模型可见输入 | instruction.md；environment/input/reference.png（仅这一张图） 与 CREDIT.txt |
| 固定输出 | output/solution.py、scene.blend、scene.glb、main.png（1000×1000）、README.md；可选 assets/ |
| 评测私有资料 | solution/reference/ 原生 GT、GLB、四视图及 audit.json；solution/provenance/ 来源许可；solution/EVALUATION.md 指标和读取方式 |
| 中文筛选稿 | instruction.zh.md，与英文要求等价，不作为额外模型输入 |
| harness | 通过仓库公共入口调用逐题原生或扩展测评；最终权重见评分说明 |

入口命令与可移植要求见 [英文 instruction](instruction.md)。最大跨度统一为 1 m，静态第 1 帧，无爆炸图要求。未给模型的其他视角不作为隐藏表面精确评分目标。详细指标见 [评测说明](solution/EVALUATION.md)。

![模型主参考图](environment/input/reference.png)

来源：[Rico Cilliers](https://polyhaven.com/a/treasure_chest)，CC0-1.0。Static evaluated geometry; uniform normalization to 1 m maximum span; new studio cameras and lighting.
