# 弹力冰球竞技场

控制圆形球拍，与简单 AI 进行借墙反弹的冰球对抗。

已纳入正式题库，任务设计可评审。L3 工程实现难度暂按 hard 标记，未经模型实测；实现范围表示设计规模，不代表实测难度。

| 项目 | 内容 |
|---|---|
| 游玩方式 | 短局、重赛和不限时练习；可调 AI 反应速度。 |
| 美术 | 基础几何、纯色材质、简单灯光，不要求外部贴图资产 |
| 实现范围 | 较小 |
| 模型输入 | 英文 instruction.md；environment/input/reference.png；environment/input/PROJECT_LAYOUT.md |
| 模型输出 | output/ue5_project/3DBenchGame.uproject；完整UE5工程与Blender源资产；output/README.md |
| 主要评测 | 碰撞反弹、进球、AI 公平性与重置 |
| 边界 | 限制球拍速度，避免鼠标瞬移制造无限冲量。 |
| 私有参考 | solution/ 仅评测设计和概念图来源，无GT工程 |

[中文 prompt](instruction.zh.md) · [English prompt](instruction.md) · [详细评测表](solution/EVALUATION.md)

Harness 将 environment/ 内容挂到模型工作区并保留 input/ 相对路径；图片必须作为图像输入提供或允许图像工具打开，不能只发送文件名。harness/ 暂空。

![模型可见概念图](environment/input/reference.png)

参考图表示视觉方向，不代表已经实现或测试过的游戏。玩法和数值以 prompt 为准。
