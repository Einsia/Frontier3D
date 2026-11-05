# 评测接口：日照教室与成排课桌

重点语义结构：桌椅阵列及通道、黑板墙、窗与暖气片、顶灯管线、日照和使用痕迹。原生模型是私有参考，不是逐顶点答案。单视图不唯一，不能把隐藏尺寸、原对象名称或原作者网格拆分作为通过条件。

| 维度 | 指标 | 实现与边界 |
|---|---|---|
| 可执行性 | 固定文件完整率、入口运行与原生重渲染成功率、缺失依赖数 | 清洁工作区按 instruction 命令运行；核对双视图来自提交工程，禁止直接拷贝参考图当输出。 |
| 结构 | 本题语义部件覆盖率、几何独立可编辑性 | 按上述清单建立评测侧区域标注；不依赖提交对象名称，不限定实现方式。 |
| 几何 | 可见区域轮廓误差、采样表面距离、深度层次和接触/穿透 | 将参考按题目尺度归一并用可见地标对齐后比较；原模型绝对坐标和隐藏表面不做硬约束。不同合理单视图解允许通过。 |
| 视觉 | 主视图构图、材质分布、光影；参考对齐后的区域图像差异 | 从提交工程重渲染；报告几何、材质、光影分项，细小文字及允许简化的细节不要求像素一致。 |
| 状态一致性 | 备用相机规定偏移、视差与遮挡一致性 | 两相机使用同一实体结构；备用视图没有目标图，不与源作者任意备用相机比较。 |
| 可维护性 | 可复现生成、可编辑主要对象、依赖局部化 | 二次执行代码得到等价场景；生成代码不能只是读取私有 GT 或联网取回原场景。 |
| 效率 | 耗时、token、工具调用、渲染及失败重试 | Harness 统一记录；未校准前不将其混入质量总分。 |

参考工程、图片与 native-audit.json 已检查可打开、无缺失活动纹理和外链库。此审计不是模型成绩。生成与测评由仓库公共入口执行，最终计分见[评分说明](../../../../../../../docs/cn/scoring.md)。几何接口描述不等于全部已实现，感知阈值保留校准限制。

## Object localization

Reference-owned key-object boxes are matched one-to-one against independently observed candidate boxes of the same class. Pair similarity uses 50% IoU, 30% center agreement and 20% size agreement. Missing and additional objects reduce localization quality. The measurement describes image-plane layout and cannot certify metric 3D depth.

Frozen key-object classes: chalkboard (30%), chair (30%), window (20%), ceiling light (20%).

Reference boxes cover visible image extents, not inferred hidden geometry. Only the listed key objects enter localization; other scene content remains in the appearance component. Blackboard excludes the map, alphabet strip and bulletin boards. Windows are three visible full-height openings, not separate upper panes. Chair instance annotation/detection remains pending.

## 评分

本题最终得分：`50% main_image + 20% localization + 20% vlm + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
