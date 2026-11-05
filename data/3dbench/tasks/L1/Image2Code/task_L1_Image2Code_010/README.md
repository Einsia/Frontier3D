# 双翼科学着陆器

多视图重建实际公开模型。重点：中央仪器甲板与设备箱、三组着陆腿脚垫、两片大型分扇区圆形太阳翼、铰接支架及可见传感器和仪器结构。圆翼为薄型框架组件而非厚圆盘，并与中央平台连接。

| 输入 | 固定输出 | 私有参考 |
|---|---|---|
| 英文 instruction、主视图和三张正交图、CREDIT.txt | output/solution.py、scene.blend、scene.glb、main.png、README.md | 归一化原模型、GLB、四视图、依赖检查和来源许可 |

仅向模型提供 instruction.md 和 environment/input；中文 instruction.zh.md 用于筛选，solution 不提供。原模型可能将多个实物部件合成网格，不能用原对象数或名称判断提交。评测按语义组成和可见形体进行；未提供的隐藏细节不作精确 GT。生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。

![主参考](environment/input/reference.png)

来源：[NASA and NASA 3D Resources contributors](https://github.com/nasa/NASA-3D-Resources/tree/11ebb4ee043715aefbba6aeec8a61746fad67fa7/3D%20Models/InSight%20Cruise%20Lander)，NASA public media (upstream: free and without copyright)。同一模型仅用于本题，不在单视图和多视图间复用。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)
