# Balenciaga 墨镜

重建墨镜的双镜片、镜框、鼻梁及可见镜腿和铰链。保留镜片曲率、框厚、边缘过渡、镜腿弯折及部件空隙，匹配展示姿态和深色反光材质，小字可简化。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[redizajnd](https://sketchfab.com/3d-models/balenciaga-sunglasses-cda3e70d71c54d12898c81531550be4c)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
