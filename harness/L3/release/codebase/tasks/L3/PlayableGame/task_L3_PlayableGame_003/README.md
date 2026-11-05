# 轨道工程沙盒

用 Blender + UE5 制作能自由组装、分级发射和查看轨道的航天沙盒。

| 项目 | 内容 |
| --- | --- |
| 模型输入 | 英文 instruction；一张概念图，仅作视觉方向参考。 |
| 模型输出 | 完整可编辑、可运行的 UE5 工程：.uproject、关卡、资产、配置、Blueprint/C++、所需依赖，以及引擎版本和操作说明。 |
| 评测参考 | 没有参考游戏或唯一飞行轨迹；按提交游戏的参数做独立物理校验，solution/ 仅有评测参考。 |

[English instruction](instruction.md) · [中文筛选版](instruction.zh.md) · [详细评测指标](solution/EVALUATION.md)

| 核心指标 | 检查内容 |
| --- | --- |
| 设计与控制 | 部件变体、自由组合、分级/分离、油门/姿态和至少 3 种有效设计。 |
| 物理自洽 | 单体引力位置/速度误差；推力、燃料、质量、降落伞与轨道显示。 |
| 状态与稳定性 | 分离体、连接、存档/失败恢复、20 Hz 基础步与时间加速。 |
| 可玩与语义一致 | 操作反馈、轨道可读性、运行性能；有对应证据时做跨引擎比较。 |

运行/加载成功率和时间、token、工具/渲染调用成本作为公共指标。

模型只接收 `instruction.md` 与 `environment/` 的内容（保留 `input/` 相对路径）；不开放整个 task 目录。`harness/` 只有 Git 占位文件，暂不实现 `declaration.py`。

输入文件：

- `environment/input/reference.png`

固定 UE5 交付结构：output/ue5_project/3DBenchGame.uproject；项目根包含 Config/、Content/，可选 Source/、Plugins/，Blender 源资产放 SourceAssets/Blender/。不提交 Binaries/、Intermediate/、Saved/、DerivedDataCache/。

## 模型可见输入

- `instruction.md`：英文实测需求；`instruction.zh.md` 是等价中文筛选稿。
- `environment/input/reference.png`：提供给模型的视觉方向图，供材质、配色、造型和画面可读性参考。
- `environment/input/PROJECT_LAYOUT.md`：固定 UE5 交付结构。

Harness 将 `environment/` 的内容放入模型工作区，保留 `input/` 路径，并将参考 PNG 作为图像输入或允许模型通过图像工具查看。不要只发送图片文件名。`solution/` 是私有评测材料，不提供给模型。

![模型可见视觉参考](environment/input/reference.png)

图片是概念参考，不代表已有可运行游戏；玩法和数值以 instruction 为准。
