# 法棍面包篮

重建图中的整组面包与篮子，包括编织篮、厚篮口及可见把手、竖放法棍和篮旁横放的面包。匹配输入中可见数量、相对高度、倾斜方向、表面割纹和金黄色烤皮。篮子需要真实深度及可读编织结构；细纤维和气孔可用材质表达，不要添加额外食物或桌面道具。

- 类别：Image2Code-SingleView；难度 medium（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Armin Rezaei](https://sketchfab.com/3d-models/baguette-basket-227e1cfecce148318531bc1b157192d7)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
