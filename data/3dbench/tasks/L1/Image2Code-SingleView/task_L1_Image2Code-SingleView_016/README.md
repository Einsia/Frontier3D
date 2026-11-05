# 人体心脏

重建心脏模型的心室、心耳、大血管分支及表面冠状血管。保留有机曲率、管口和肌肉与脂肪色区，不凭空添加剖面或内部解剖；本题仅为视觉重建。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Rudy](https://sketchfab.com/3d-models/human-heart-2edbedffae6b49ee97f919a8528329ba)，CC-BY-4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
