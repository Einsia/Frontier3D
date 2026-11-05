# 可动上翻柜门铰链与伸缩撑杆

重建带上翻框门的壁柜、两侧上部铰链和两根带转动接头的伸缩撑杆。保留柜腔、薄板、门框与半透明门芯。门绕顶部铰链轴旋转；撑杆在柜体和门的连接点转动，并沿自身轴向伸缩、保持连接。不能用整门平移或拉伸刚性零件伪造开门。不要求气压或弹簧力仿真。

- 类别：Image2Code；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；四张对象视图加两张运动姿态图和 motion.json。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[fiono](https://sketchfab.com/3d-models/spring-hinges-engsel-pegas-rak-piring-670da4b6815e4dff9c24d8af37c99fb4)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Resampled source frames 1..50 to task frames 1..61 and mirrored to frame 121; retained animated hinge/strut components.
