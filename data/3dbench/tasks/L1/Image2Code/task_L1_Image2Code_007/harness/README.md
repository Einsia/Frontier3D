# Image2Code 007：八角飞檐宫灯

本题提供独立规格和原生测量入口；生成、容器、超时、重试、基准/seed 执行在项目外层 `orchestrator/`，共享取证在 `src/evaluator/`。原生测量覆盖范围见下文；最终评分还包含共享视觉与细节测评。

本题尺度 1000 mm，2% 容差；静态帧 1，不要求爆炸。必交主图 1000×1000；读取实际 PNG 尺寸及原生保存的 Cycles/AgX/曝光 0、相机与灯光事实。允许可分离网格岛，不套用机械题固定件数/逐对象闭合门。

独立要求：
- `visible_components`（missing）：Reconstruct the complete octagonal lantern. Preserve the eight-sided timber frame, recessed pale panels, concentric polygonal top frame and raised centre cap, outward curling corner brackets, downward-curving feet, hanging cords, beads and red tassels. Keep the repeated elements evenly distributed around the eight sides while matching the visible proportions and overlaps. The curved wooden ornaments, frame depth and tassel volumes need real geometry. Panel paintings may be simplified into sparse floral marks with similar colour and placement; reproducing their exact brushwork is not required. This is an unlit display object, so no electrical or light-emission mechanism is needed.；尚未接入本题语义部件识别、局部特征与连接判定；不能以非空网格/全图相似度代替。
- `editable_3d`（partial）：真实三维，可分别编辑语义部件；允许对象层级或可分离网格岛；不得用图像平面或不透明无结构块冒充；只核验非平面网格及基础可编辑性，尚不能识别语义分组或薄壳冒充。
- `overall_span`（complete）：模型最大整体跨度 1000 mm，容差 2%，不计相机/灯光
- `units_orientation`（partial）：米制导出，Z 向上；使用经过场景单位转换的真实顶点计算物理跨度，未绑定本题语义朝向。
- `proportions`（partial）：按公开主视图、正/侧/顶视图保持轮廓、部件比例、遮挡与层次；合理补全未见表面；全图 SSIM 仅作整体外观证据，其他视图/局部比例及三维一致性尚未绑定。
- `connections`（missing）：可见孔隙、薄结构、连接点和重叠层次为真实几何；避免刚性部件严重穿透或悬空，允许设计接头和软线缆；未绑定本题部件、孔隙和真实接触/碰撞关系。
- `materials`（partial）：匹配主导材质、颜色及可见表面特征；细微磨损、字体/标记按本题允许范围简化；参考图对拍不等于角色材质、BSDF 或灯光参数正确；须补有效材质与局部外观判定。
- `primary_view`（partial）：使用与 reference.png 匹配的相机生成 main.png；相机存在与提交图 SSIM 已接入；相机匹配阈值及从该场景可信重渲染核对仍缺失。
- `render_settings`（complete）：原生场景保留 1000×1000 有效分辨率、Cycles、AgX、曝光 0
- `camera_lighting`（partial）：场景保留审阅相机及中性棚拍照明；取证保存相机及可见灯数量；中性照明/环境光的实际外观尚待判定，不把灯对象数量当照明正确性。
- `main_png`（complete）：交付可解码的 PNG 主图，实际像素为 1000×1000
- `static_pose`（partial）：帧 1 保存最终静态姿态，GLB 导出同姿态；不要求爆炸、动画或模拟；已配置题目帧策略与独立 seed 比较；姿态/语义组、可读性、完整保形及材质等价未正式标定。
- `glb_readable`（complete）：scene.glb 可重新导入
- `glb_equivalence`（partial）：原生与 GLB 在交付姿态的几何、尺度和可表达材质一致；跨格式诊断已复用，但本题等价阈值和角色/材质映射未标定。
- `reconstruction`（partial）：便携代码在清洁环境重建全部交付；不依赖旧输出、个人路径或外部下载源模型/源视图；外层冻结公开输入及源码、禁网执行、重跑已有支持；完整依赖/来源语义和图像与场景一致性仍需验收。
- `instructions`（partial）：README 说明运行与依赖；仅核验可读取，未判定说明内容。

共 16 条要求：完整 4、部分 10、缺失 2；未覆盖保留在固定分母。SSIM 比较提交的主图与冻结公开参考，只是外观代理，不能证明图像出自 scene.blend；可信重渲染一致性、局部语义、有效材质和阈值仍待补齐。辅助固定视图仅用于审阅，未拿隐藏相机/源拓扑作评分目标。

输入仅公开题面和 manifest allowlist。公开正/侧/顶视图保留在输入；主图 SSIM 仅衡量相应视图的外观，其他视图和局部形体按各分项合同检查。当前 inspector 的曲线/未实体化实例限制仍报告工具缺口，不暗中要求隐藏机械结构。

运行：`.venv/bin/python -m orchestrator run --task L1/Image2Code/task_L1_Image2Code_007 --submission <源码目录>`。结果归档 `data/task_runs`；测试候选与真实生成分开，未测得的 seed 不移出分母。

## 评分

本题最终得分：`50% main_image + 20% localization + 20% vlm + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
