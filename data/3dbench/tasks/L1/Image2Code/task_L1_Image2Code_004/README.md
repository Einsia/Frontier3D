# 老旧风力涡轮塔

按给定姿态重建旧风力涡轮塔，包括支撑框架、风轮叶片和轮毂、粗管与斜撑、底部机械和基座。保留不对称特征和清楚的间隙，不能把框架做成实心块。匹配主要锈蚀金属外观。本题只重建静态姿态，不要求源动画、发电或结构仿真。

- 类别：Image2Code；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；四张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Helley](https://sketchfab.com/3d-models/old-wind-turbine-tower-806388e5dcda4c8f960a1bbd6682649e)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Baked the evaluated source pose at frame 1; source animation omitted from the static task.
