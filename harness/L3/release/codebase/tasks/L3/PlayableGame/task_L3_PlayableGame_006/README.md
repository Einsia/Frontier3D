# 无尽迷你高尔夫

瞄准、蓄力、击球，用尽量少的杆数连续挑战新球道。

已纳入正式题库，任务设计可评审。L3 工程实现难度暂按 hard 标记，未经模型实测；实现范围表示设计规模，不代表实测难度。

| 项目 | 内容 |
|---|---|
| 游玩方式 | 种子生成球道；每洞结束后无尽续关，也可重打同一洞。 |
| 美术 | 基础几何、纯色材质、简单灯光，不要求外部贴图资产 |
| 实现范围 | 较小 |
| 模型输入 | 英文 instruction.md；environment/input/reference.png；environment/input/PROJECT_LAYOUT.md |
| 模型输出 | output/ue5_project/3DBenchGame.uproject；完整UE5工程与Blender源资产；output/README.md |
| 主要评测 | 击球冲量、碰撞反弹、进洞与杆数状态 |
| 边界 | 需要验证生成球道可通行；不把最优杆数作为隐藏标准。 |
| 私有参考 | solution/ 仅评测设计和概念图来源，无GT工程 |

[中文 prompt](instruction.zh.md) · [English prompt](instruction.md) · [详细评测表](solution/EVALUATION.md)

Harness 将 environment/ 内容挂到模型工作区并保留 input/ 相对路径；图片必须作为图像输入提供或允许图像工具打开，不能只发送文件名。harness/ 暂空。

![模型可见概念图](environment/input/reference.png)

参考图表示视觉方向，不代表已经实现或测试过的游戏。玩法和数值以 prompt 为准。
