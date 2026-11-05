# 综合力量训练器

重建健身器材：主承重框架、坐垫与靠垫、杠杆臂和把手、可见滑轮与拉索路径、配重组或阻力外壳以及稳定支脚。保留框架空隙、合理连接和可见布线。匹配浅色主架、深色软垫和红色包边。本题是静态模型，不要求人体、受力仿真或隐藏阻力机构。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[Gerhald](https://sketchfab.com/3d-models/gym-trainer-9cb04641558e40dbbee9f61ac55fdcb5)，CC BY 4.0。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Removed a detached 10-triangle source fragment floating above the intact exercise machine; original download retained unchanged.
