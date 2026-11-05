# 零重力法杖反冲对战

用射击反作用力改变角色位置与姿态的卡通对战游戏。有限转向、能量与三种特殊攻击共同形成攻防选择，包含遵循同一规则的 AI 和完整比赛流程。

| 模型输入 | 交付 | 评测侧 |
|---|---|---|
| 英文 instruction.md、视觉参考图和交付结构说明；无初始工程或规格 JSON | output 下可运行 UE5 工程、Blender 源资产、启动说明 | 无标准游戏 GT；solution 仅存评测设计，harness 暂空 |

只发送 instruction.md 和 environment 中的模型输入，中文用于筛选。当前是任务设计，不是已经实现或测过的游戏。未要求模型解释迁移过程。

[英文要求](instruction.md) · [中文要求](instruction.zh.md) · [评测接口](solution/EVALUATION.md)

固定 UE5 交付结构：output/ue5_project/3DBenchGame.uproject；项目根包含 Config/、Content/，可选 Source/、Plugins/，Blender 源资产放 SourceAssets/Blender/。不提交 Binaries/、Intermediate/、Saved/、DerivedDataCache/。

## 模型可见输入

- `instruction.md`：英文实测需求；`instruction.zh.md` 是等价中文筛选稿。
- `environment/input/reference.png`：提供给模型的视觉方向图，供材质、配色、造型和画面可读性参考。
- `environment/input/PROJECT_LAYOUT.md`：固定 UE5 交付结构。

Harness 将 `environment/` 的内容放入模型工作区，保留 `input/` 路径，并将参考 PNG 作为图像输入或允许模型通过图像工具查看。不要只发送图片文件名。`solution/` 是私有评测材料，不提供给模型。

![模型可见视觉参考](environment/input/reference.png)

图片是概念参考，不代表已有可运行游戏；玩法和数值以 instruction 为准。
