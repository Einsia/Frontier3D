# DJI Mavic 3 无人机

按展开的静态姿态重建无人机：流线机壳、四臂与电机座、可见桨叶、起落支撑、前部相机云台以及主要接缝和传感器凹口。保留机臂角度、对称关系和薄构件之间的空隙。匹配灰色机壳及深色部件。源模型为摄影测量结果，不需复制扫描噪声或原拓扑，不要求飞行、折叠或电机动画。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Metazeon](https://sketchfab.com/3d-models/dji-mavic3-classic-dji-drone-f398bcd363ce43f896722cf349ef5c92)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras.
