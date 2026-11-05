# 石砌地牢：恢复拱道照明

拱道浮雕明暗；前后纵深；中性照明；灯位与几何材质保持。输入：修改后的原生场景、单张完整参考图和文字修改要求。输出：编辑代码、Blender 工程和双视图。

| 内容 | 路径与用途 |
|---|---|
| 模型输入 | instruction.md；environment/input 映射为工作区 input；input/initial.blend, input/reference.png, input/SOURCE.txt |
| 统一交付 | output/solution.py、scene.blend、main.png、alternate.png、README.md；可选 output/assets/ |
| 私有参考 | solution/reference/scene.blend、main.png、native-audit.json；annotations 内保存删除目标或原参数及保持性基线 |
| 筛选与评测 | instruction.zh.md 是等价中文；solution/EVALUATION.md 是 evaluator 接口说明；生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../docs/cn/scoring.md)。 |

原生完整工程及目标参数仅供评测侧；先检查非目标内容保持，再评价局部修改。 solution 不提供给模型。

![左为完整参考，右为实际输入状态](solution/reference/comparison.png)

来源：[cheerful sprite](https://opengameart.org/content/medieval-dungeon-interior)，CC0-1.0，无署名义务。参考几何来自所列作者的公开资产。资产依赖、取景、去重与输入构造记录见 provenance。
