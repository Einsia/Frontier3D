# 东蓝鸲

重建风格化蓝鸟的圆润躯干、头喙、双翼、收尖尾部及可见的抓握脚。保留蓝色、暖色胸腹和浅色腹底分区、眼位与脚部空隙，细小羽毛可简化。

- 类别：Image2Code-SingleView；难度 hard（设计预估，未实测校准）。
- 模型输入：[英文 instruction](instruction.md) 与 environment/input/；仅一张对象视图。
- 中文筛选稿：[instruction.zh.md](instruction.zh.md)。
- 固定输出：output/solution.py、scene.blend、scene.glb、main.png、README.md。
- 私有资料：solution/source/model.glb、solution/reference/ 与 solution/provenance/；[评测说明](solution/EVALUATION.md)。
- 生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![参考图](environment/input/reference.png)

来源：[kenchoo](https://sketchfab.com/3d-models/eastern-blue-bird-c646531de6a3494faeaf2d3ce91b9dd2)，CC Attribution。Imported official GLB; packed textures; normalized the maximum span to 1 m; added new studio lighting and reference cameras. Baked the evaluated source pose at frame 1; source animation omitted from the static task.


参考生成已排除导入器创建的骨骼显示辅助对象；原始 GLB 保持不变。
