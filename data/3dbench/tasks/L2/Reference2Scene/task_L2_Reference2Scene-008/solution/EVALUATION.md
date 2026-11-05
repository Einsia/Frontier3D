# 评测接口：砖拱旧货店与密集陈列

公开要求全部在 instruction.md。重点：砖拱梁柱；前后房间；开放陈列架；器皿杂物分组；暖光与遮挡。原生工程为私有参考；单视图重建不唯一，隐藏几何和源拓扑不能作为硬性答案。

| 维度 | 要测什么 | evaluator 如何接入 |
|---|---|---|
| 文件与可执行性 | 固定输出齐全；脚本能从干净输入执行；无缺失依赖 | 按 instruction 命令执行，离线重开 scene.blend 并重新渲染两张图；核对提交图来自该工程。 |
| 需求覆盖 | 上述语义结构和明确尺寸/编辑范围 | 将题面清单映射为评测侧区域或几何测量，不依赖模型自取对象名。 |
| 几何与空间 | 有体积的结构、开口与厚度、支撑/接触、穿透和空间层次 | 表面采样、BVH 和连通/间距测量。按题目尺度和可见地标对齐后比较可见表面；隐藏面允许合理解。 |
| 视觉 | 构图、轮廓、材质颜色、受光和阴影层次 | 使用提交工程重渲染；分别报告区域轮廓、Lab 色彩及亮暗分布。允许简化的文字或小细节不按像素硬判。 |
| 跨视角一致 | 同一真实三维场景形成双图，相机满足题面 | 检查相机矩阵与几何视差，防止图像平面或分别为两张图建立不同场景。 |
| 可复现与可编辑 | 重复执行稳定、主要结构可编辑、资产自包含 | 第二次从干净目录执行，比较场景结构及渲染；不能读取私有 solution 或从网络取回源工程。 |
| 效率 | 时间、token、调用次数、失败重试 | Harness 统一采集，和质量分开汇报。 |

下表描述测量接口；实际计分覆盖以逐题合同为准。参考源对象名和网格划分不构成额外硬约束。容差与区域权重保留校准限制，未实现指标须单列。

## Object localization

Reference-owned key-object boxes are matched one-to-one against independently observed candidate boxes of the same class. Pair similarity uses 50% IoU, 30% center agreement and 20% size agreement. Missing and additional objects reduce localization quality. The measurement describes image-plane layout and cannot certify metric 3D depth.

Frozen key-object classes: archway (40%), shelf (35%), pendant lamp (25%).

Reference boxes cover visible image extents, not inferred hidden geometry. Only the listed key objects enter localization; other scene content remains in the appearance component. Archway is the whole central arch-and-opening envelope. Shelves are five open display units, including clipped foreground units and distant visible units; clocks, closed cabinets and isolated posts are excluded. These classes await detector calibration.

## 评分

本题最终得分：`50% main_image + 20% localization + 20% vlm + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
