# 科隆大教堂微缩模型

将教堂作为一件建筑缩尺模型重建。保留前部双高尖塔、中殿与横厅、阶梯屋顶体量、重复扶壁和小尖塔、大门洞与窗凹口以及图中基座。主要镂空和重复建筑浮雕要有真实几何，细雕像和微小砖缝可简化。不要求内部房间或可行走场景。

- 类别：Image2Code；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；四张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Shahriar Shahrabi](https://sketchfab.com/3d-models/cologne-cathedral-200bac005a2e42458e64060d9719cd06)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
