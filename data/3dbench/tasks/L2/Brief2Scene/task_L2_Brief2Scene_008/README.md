# 砂岩峡谷通道与荒漠植被

贯通通道；层理岩壁；独立石柱；天然岩拱；荒漠植被三组；高低双视角。输入：纯文字要求，不给参考图和原模型。输出：生成代码、Blender 工程和双视图。

| 内容 | 路径与用途 |
|---|---|
| 模型输入 | instruction.md；environment/input 映射为工作区 input；无输入资产 |
| 统一交付 | output/solution.py、scene.blend、main.png、alternate.png、README.md；可选 output/assets/ |
| 私有参考 | solution/reference/scene.blend、main.png、native-audit.json；provenance 保存来源、许可与处理记录 |
| 筛选与评测 | instruction.zh.md 是等价中文；solution/EVALUATION.md 是 evaluator 接口说明；生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。 |

作者原场景仅供理解风格和设计复杂度，不是布局或像素 GT；按公开题面约束评价允许的不同布局。 solution 不提供给模型。

![仅供评审的原作者场景，不提供给模型](solution/reference/main.png)

来源：[loafbrr_1](https://opengameart.org/content/canyon-terrain-asset)，CC0-1.0，无署名义务。参考几何来自所列作者的公开资产。资产依赖、取景、去重与输入构造记录见 provenance。
