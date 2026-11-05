# 榴莲

重建带刺榴莲，包括不规则圆鼓果体、短果梗、覆盖表面的尖刺和图中明显的瓣缝。尖刺要影响轮廓并形成起伏，不能只贴平面纹理；刺的大小和朝向应随曲面合理变化。匹配主要果皮配色和果梗材质，不要求精确刺数或微小气孔。

- 类别：Image2Code-SingleView；难度 medium（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Laithai](https://sketchfab.com/3d-models/durian-the-king-of-fruits-62cc563e52514fa9b2e3dfdfc09e5377)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
