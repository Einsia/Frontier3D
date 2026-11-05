# 现代浴室：补建浴缸

在完整艺术家场景的缺件版本中补建目标物体，重点是浴缸内部凹腔、连续外壳、圆滑口沿及与地面的接触。已检查实际缺件输入、保留网格、纹理与原生文件；生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

| 输入 | 输出 | 私有参考 |
|---|---|---|
| 英文 instruction；缺件 initial.blend；一张完整 reference.png；许可 | 固定 output/solution.py、scene.blend、main.png、alternate.png、README.md | 完整 scene.blend、原渲染、转换记录、目标索引、许可与来源 |

仅向模型发送 instruction.md 和 environment 内容；将 environment/input 映射为工作区 input。instruction.zh.md 用于中文筛选，solution 不得挂载给受测模型。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测说明](solution/EVALUATION.md)

![完整参考图](environment/input/reference.png)

![实际缺件输入](solution/reference/initial.png)

来源：Mareck，[Contemporary Bathroom](https://www.blendswap.com/blends/view/75302)，CC0-1.0。一套场景只对应本题。缺件图需从实际输入工程渲染，不在参考图上涂抹遮挡。
