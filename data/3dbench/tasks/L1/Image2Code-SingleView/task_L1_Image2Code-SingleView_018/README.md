# 边境牧羊犬

按展示姿态重建边境牧羊犬的口鼻、耳、胸、爪、腿与尾，匹配黑白毛色分区。毛发下保留连贯躯体；毛发允许用分层几何或局部材质简化，但须保留蓬松轮廓，不能用照片平面代替。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[imdjs](https://sketchfab.com/3d-models/border-collie-dogmesh-hair-516a1a06c6f248b6b8c28801eb1397ac)，CC Attribution。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Increased Cycles transparent_max_bounces to 128 for the source layered mesh fur; original materials and geometry retained.
