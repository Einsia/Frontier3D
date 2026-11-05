# 工业双目显微镜

多视图重建实际公开模型。重点：马蹄形底座、立柱、载物台与夹片、可转物镜盘、双目镜、调焦旋钮及线缆。保留台下净空、偏置镜头和控制件套叠圆柱。

| 输入 | 固定输出 | 私有参考 |
|---|---|---|
| 英文 instruction、主视图和三张正交图、CREDIT.txt | output/solution.py、scene.blend、scene.glb、main.png、README.md | 归一化原模型、GLB、四视图、依赖检查和来源许可 |

仅向模型提供 instruction.md 和 environment/input；中文 instruction.zh.md 用于筛选，solution 不提供。原模型可能将多个实物部件合成网格，不能用原对象数或名称判断提交。评测按语义组成和可见形体进行；未提供的隐藏细节不作精确 GT。生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![主参考](environment/input/reference.png)

来源：[Lukas Walzer](https://polyhaven.com/a/industrial_microscope)，CC0-1.0。同一模型仅用于本题，不在单视图和多视图间复用。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)
