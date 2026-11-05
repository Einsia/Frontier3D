# 球壳悬浮机器人

多视图静态对象重建，难度 hard（设计预估）。按参考姿态重建悬浮机器人。保留分层球形机身、分隔的壳带、两侧圆形外壳与凹入机械区、前部光学开口、带关节的侧臂和弯曲爪板。按图恢复真实间隙、遮挡、收分与面板厚度。机器人不需要地面支撑，但臂和爪板应有合理的机身连接。材质采用图中的纯橄榄绿色，不要求文字、警示条纹与旧化，不要添加腿或底座。

| 项目 | 内容 |
|---|---|
| 模型可见输入 | instruction.md；environment/input/reference.png、front.png、side.png、top.png 与 CREDIT.txt |
| 固定输出 | output/solution.py、scene.blend、scene.glb、main.png（1000×1000）、README.md；可选 assets/ |
| 评测私有资料 | solution/reference/ 原生 GT、GLB、四视图及 audit.json；solution/provenance/ 来源许可；solution/EVALUATION.md 指标和读取方式 |
| 中文筛选稿 | instruction.zh.md，与英文要求等价，不作为额外模型输入 |
| harness | 通过仓库公共入口调用逐题原生或扩展测评；最终权重见评分说明 |

入口命令与可移植要求见 [英文 instruction](instruction.md)。最大跨度统一为 1 m，静态第 1 帧，无爆炸图要求。评测覆盖四个公开视角可见表面的并集。详细指标见 [评测说明](solution/EVALUATION.md)。

![模型主参考图](environment/input/reference.png)

来源：[Quandtum](https://opengameart.org/content/ba-2-blast-all-bot-mark-2)，CC0-1.0。Static evaluated geometry; uniform normalization to 1 m maximum span; new studio cameras and lighting. All inherited texture maps removed because the author identifies third-party texture samples without their licenses. Plain olive material created for this task. No upstream textured .blend or archive redistributed.
