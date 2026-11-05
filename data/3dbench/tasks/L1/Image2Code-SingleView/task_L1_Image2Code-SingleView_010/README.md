# 大卫头像

重建大卫头像胸像：倾斜头部、额头眉弓、眼窝、鼻唇和下巴、可见耳廓、连续颈部和肩部切面以及成簇卷发。匹配面部比例和主要曲面的连续过渡。卷发需要层叠曲面体积与沟槽，不能只画轮廓线。采用参考图中的浅色雕塑材质，不要求原雕像拓扑一致。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[1d_inc](https://sketchfab.com/3d-models/david-head-39a4d01bef37495cac8d8f0009728871)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
