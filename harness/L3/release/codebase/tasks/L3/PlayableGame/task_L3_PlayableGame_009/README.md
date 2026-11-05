# 多米诺连锁游乐场

自由摆放骨牌、坡道和滚珠，轻推第一块看连锁反应。

已纳入正式题库，任务设计可评审。L3 工程实现难度暂按 hard 标记，未经模型实测；实现范围表示设计规模，不代表实测难度。

| 项目 | 内容 |
|---|---|
| 游玩方式 | 随意搭建、触发、撤回到初态再改造；本地保存作品。 |
| 美术 | 基础几何、纯色材质、简单灯光，不要求外部贴图资产 |
| 实现范围 | 中等 |
| 模型输入 | 英文 instruction.md；environment/input/reference.png；environment/input/PROJECT_LAYOUT.md |
| 模型输出 | output/ue5_project/3DBenchGame.uproject；完整UE5工程与Blender源资产；output/README.md |
| 主要评测 | 接触触发、物理连锁、初态恢复 |
| 边界 | 需要合理的质量和间距，不能按时间表依次倒下。 |
| 私有参考 | solution/ 仅评测设计和概念图来源，无GT工程 |

[中文 prompt](instruction.zh.md) · [English prompt](instruction.md) · [详细评测表](solution/EVALUATION.md)

Harness 将 environment/ 内容挂到模型工作区并保留 input/ 相对路径；图片必须作为图像输入提供或允许图像工具打开，不能只发送文件名。harness/ 暂空。

![模型可见概念图](environment/input/reference.png)

参考图表示视觉方向，不代表已经实现或测试过的游戏。玩法和数值以 prompt 为准。
