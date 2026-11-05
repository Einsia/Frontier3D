# 平台堆塔

简约几何风格的单机物理堆塔游戏。玩家在固定平台上操控长方条、方块、圆柱和楔形块，释放后交给刚体物理系统，连续堆叠并以最高稳定高度计分。

| 模型输入 | 交付 | 评测侧 |
|---|---|---|
| 英文 `instruction.md`；`environment/input/reference.png`；`environment/input/PROJECT_LAYOUT.md` | `output/ue5_project/3DBenchGame.uproject`、Blender 源资产和 `output/README.md` | 按物理、稳定判定、计分、复现和流程评测；无唯一视觉 GT |

中文 instruction 用于筛选，英文 instruction 用于实测。不得提交生成的 `Binaries/`、`Intermediate/`、`Saved/` 或 `DerivedDataCache/`。

## 模型可见输入

- `instruction.md`：英文实测需求；`instruction.zh.md` 是等价中文筛选稿。
- `environment/input/reference.png`：提供给模型的视觉方向图，供材质、配色、造型和画面可读性参考。
- `environment/input/PROJECT_LAYOUT.md`：固定 UE5 交付结构。

Harness 将 `environment/` 的内容放入模型工作区，保留 `input/` 路径，并将参考 PNG 作为图像输入或允许模型通过图像工具查看。不要只发送图片文件名。`solution/` 是私有评测材料，不提供给模型。

![模型可见视觉参考](environment/input/reference.png)

图片是概念参考，不代表已有可运行游戏；玩法和数值以 instruction 为准。
