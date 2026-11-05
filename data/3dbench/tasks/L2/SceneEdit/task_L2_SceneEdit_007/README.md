# 卡通咖啡馆：补回吧台与咖啡机

在真实作者场景中完成局部修改，重点：连续吧台、圆弧端部、台面厚度、咖啡机多部件与服务通道。

| 输入 | 固定输出 | 私有参考 |
|---|---|---|
| 英文 instruction、修改后的 initial.blend、单张完整 reference.png、CREDIT.txt | output/solution.py、scene.blend、main.png、alternate.png、README.md | 完整工程及渲染、实际输入渲染、目标范围及初始保持性摘要、原始参数与来源证据 |

environment/input 映射为工作区 input，solution 不提供给模型。中文 instruction.zh.md 用于筛选。生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![完整参考](environment/input/reference.png)

![实际输入状态](solution/reference/initial.png)

素材：[Kenney](https://kenney.nl/assets/furniture-kit)，CC0-1.0。源场景仅用于此题。已验证 31 个保留网格的几何与变换不变；目标以外材质、主相机及渲染设置保持一致。数据审计不代表模型成绩。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)
