# 骆驼

重建参考中的骆驼，保留弯曲长颈、头耳、驼峰、四肢站姿、尾部和花纹鞍毯。匹配可见轮廓、比例、毛发与色区。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[eb78](https://sketchfab.com/3d-models/camel-99af7daa5baf450ea7b809937937e6d5)，CC Attribution。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Baked the evaluated source pose at frame 1; source animation omitted from the static task.


参考生成已排除导入器创建的骨骼显示辅助对象；原始 GLB 保持不变。
