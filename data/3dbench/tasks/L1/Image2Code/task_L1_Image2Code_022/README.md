# 三角钢琴

重建三角钢琴的弧形琴体、打开的琴盖与撑杆、键盘、可见内部结构、琴腿和踏板。保留外轮廓、盖角、琴键间距和琴底空隙，细琴弦可简化但保留走向，不要求演奏机构。

- 类别：Image2Code；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；四张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[farhad.Guli](https://sketchfab.com/3d-models/grand-piano-371090c279ff4e77a59acdebc25b5892)，CC-BY-4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
