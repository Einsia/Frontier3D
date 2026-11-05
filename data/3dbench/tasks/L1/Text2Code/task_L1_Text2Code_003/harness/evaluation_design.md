# L1/Text2Code/task_L1_Text2Code_003：逐题测评设计

依据：评测接口：丝杠驱动滑台。来源行号/原文和哈希见 evaluation_design.json。

本文件描述原生测量接口；实际实现覆盖见 eval_spec.json，最终计分按共享评分合同执行。

本题重点：丝杠、滑台及支撑的实心/孔道截面；螺母和导向装配相对位姿

| 来源行 | 维度/指标 | 方法 | 状态 |
| --- | --- | --- | --- |
| 7 | 可执行性 / 固定入口、原生工程和 GLB 有效 | execution, delivery, state | 待逐项实现/验收 |
| 8 | 结构 / 零件数量、闭合连通、语义层级 | solid, editable | 待逐项实现/验收 |
| 9 | 几何 / prompt 的尺寸、孔径、台阶、盲孔与贯通关系 | numeric, assembly | 待逐项实现/验收 |
| 10 | 装配 / 同轴、孔轴对应、指定间隙和接触 | assembly | 待逐项实现/验收 |
| 11 | 双状态 / 帧 1/61 几何保持与恢复 | state, delivery, numeric | 待逐项实现/验收 |
| 12 | 视觉 / 材料类别和三维可读性 | numeric_material | 待逐项实现/验收 |
| 13 | 效率与稳定 / 时间、token、调用、重试和复现 | cost, execution | 待逐项实现/验收 |

## 测量方案

- `execution`：外层清洁基准+seed 0/1/2执行；原生/导出独立加载；交付哈希绑定，失败不删除。
- `delivery`：独立重新导入GLB比较世界尺度、几何/孔槽/姿态和可表达材质；不可表达的程序化节点单列，不自动烘焙位图。
- `state`：按本题帧策略比较局部形状、身份和恢复；GLB对帧1；不要求参考的爆炸方向或距离。
- `solid`：求值世界空间网格；连通、流形、退化、自交、有限正体积；图像扫描/曲面题不强制闭合或固定对象数。
- `editable`：检查实际可编辑几何/部件组织及代码重建；对象名、变量名、顶点顺序不作为正确性真值。
- `numeric`：按本题数值条款拟合实际平面/圆柱/截面；报告mm误差和容差；孔槽用边界+占用/连通检查，AABB仅作粗筛。
- `assembly`：以几何匹配角色/对称置换；一次整体刚体对齐后测轴线、接触、规定间隙和实际实体穿透，禁止逐件配准。
- `numeric_material`：只检查明确配色/金属度等可测材质参数及实际分配；不以相机、背景、整体文本语义或私有示意图像素相似度给Text2Code评分。
- `cost`：保留成功、失败、重试和反馈各轮时间/token/调用；未知token为null；成本与质量分列。

## 逐题几何测量范围

11件丝杠滑台：底板、2导杆、2衬套、光杆、螺母块、平台、2端座、手轮。

以下说明几何测量与验收范围；已实现指标以逐题配置为准，公开约束见 instruction。

- `dimensions_surfaces`：导杆Ø8×150、光杆Ø10×182、衬套Ø18/8.4×40；螺母块24×22×18和平台58×86×6各自测量。
- `features_topology`：端座Y−30/0/+30的Ø8.4/10.4/8.4三条X向通孔，螺母及手轮孔独立检查；不要求螺纹。
- `assembly_relationships`：轴Z26、端座X±76、平台中心Z38；平台底须接触衬套和螺母块，光杆到手轮外端面，不逐件对齐。

- 容差：尺寸与装配位置各0.3 mm；角度误差另报，不杜撰角度容差。
- 坐标：只作EVALUATION允许的一次整体对齐；001限平移/绕Z旋转，015允许自由原点；保留Z向上，不缩放、不逐件配准。
- 当前：已有通用/代理检查；以下专属方法尚未完整实现和验收。

### 证据与执行约定

- 角色按实际形状/尺寸/配合联合匹配，允许同类对称置换；缺件、重复件、歧义单列，不读对象名或源变量作为真值。
- 实际求值世界网格（m）测量并换算mm；原生与GLB分别取证，绑定资产/指令/规格/设计/参考哈希。
- 拟合只确定特征坐标；完整边界/壁面误差界和空域连通证据检出切片间缺陷，不用有限采样通过声明全域正确。
- 返回测量值、单位、目标、误差区间、容差、对象/面域、来源和passed/failed/not_measurable/infrastructure_error；超预算不能通过。
- 每个seed与基准使用同一质量入口；状态遵循本题帧策略，重现成功不代替质量通过。

### 本题验收控制

- 正例：公开要求生成的正确候选，不加载私有target；等价重三角化/圆周密度变化与合法同类件置换；各独立尺寸在容差内且组合同时偏移，不引入隐藏更严门。
- 反例：平台悬浮；端座中心孔盲孔；一根导杆移到错误Y；光杆未到手轮端面。。
- 边界：逐尺寸t−ε/t/t+ε（ε大于证明误差），半径和直径不混用；最后seed单独破坏一项，其余seed正常；缺证据/来源漂移/预算不足均不能判通过。

### 剩余工作

- 按三个本题组逐项补测量及以上正反例；已有专项不代表整个组均完成
- 实际角色材质参数/赋值与一般程序化材质等价；不以禁位图门替代颜色或保持性
- 独立编辑/装配状态、跨格式与完整交付要求；新候选基准及全部seed冻结验收
- 容差以题面为准；未规定的连续分归一化/阈值/材料数值需pilot校准

原生任务符合度检查包括已实现的尺寸、孔道、装配、材质和状态指标；视觉判断不能替代精确几何测量。最终总分使用共享评分合同。


## 本题边界

- 原生帧：`[1, 61, 1]`；GLB：帧1。
- 必须产物：`solution.py, scene.blend, scene.glb, README.md`。
- 期望实体件数：11。
- 候选禁止图片纹理/HDRI，允许纯色与程序化节点；私有参考保持原样。该用户新规则优先于旧提交模板中的 optional textures。
- 材质是否符合要求与是否使用位图分别判定；程序化细纹不能代替真实孔槽/厚度。
- 延期：整体场景是否符合文本描述的ViT/语义评分；不延期明确尺寸、孔槽和装配数值。

## 逐要求测量合同（第二轮，2026-10-05）

合同为实施设计，不注册新指标、不改权重。完整机器数据见JSON的measurement_contract。

### 角色与数值锚点

- 角色（不是对象命名要求）：base×1；guide_rod×2；sleeve×2；lead_rod×1；nut_block×1；platform×1；end_support×2；handwheel×1。
- 显式数值锚点不是完整规格；完整要求见requirement_contracts和全部公开条款。剩余位置/特征仍须逐条绑定，不能只实现此表就宣称整题通过。

| 特征 | 公开标称值（mm） | 比较基准 | 公差（mm） |
| --- | --- | --- | --- |
| base.size | [170, 100, 6] | 公开标称 | 0.3 |
| guide.diameter | 8 | 公开标称 | 0.3 |
| guide.length | 150 | 公开标称 | 0.3 |
| sleeve.outer_diameter | 18 | 公开标称 | 0.3 |
| sleeve.bore_diameter | 8.4 | 公开标称 | 0.3 |
| sleeve.length | 40 | 公开标称 | 0.3 |
| lead.diameter | 10 | 公开标称 | 0.3 |
| lead.length | 182 | 公开标称 | 0.3 |
| nut.size | [24, 22, 18] | 公开标称 | 0.3 |
| nut.bore_diameter | 10.4 | 公开标称 | 0.3 |
| platform.size | [58, 86, 6] | 公开标称 | 0.3 |
| end_support.size | [12, 90, 36] | 公开标称 | 0.3 |
| end_support.bore_diameters | [8.4, 10.4, 8.4] | 公开标称 | 0.3 |
| wheel.outer_diameter | 36 | 公开标称 | 0.3 |
| wheel.bore_diameter | 10.4 | 公开标称 | 0.3 |
| wheel.width | 6 | 公开标称 | 0.3 |
| guide.centers_y | [-30, 30] | 公开标称 | 0.3 |
| rod.axis_z | 26 | 公开标称 | 0.3 |
| platform.center | [0, 0, 38] | 公开标称 | 0.3 |
| end_support.centers_x | [-76, 76] | 公开标称 | 0.3 |
| end_support.center_z | 24 | 公开标称 | 0.3 |
| wheel.center | [88, 0, 26] | 公开标称 | 0.3 |

### 本题关系约束

- 平台底与两衬套和螺母块接触；端座底接底板
- 三杆分别穿端座对应孔，光杆到手轮外端面；不要求螺纹

### 逐要求接线

| 要求ID | 方法接口 | 现有实现声明 |
| --- | --- | --- |
| part_roles | editable, roles | partial |
| base | features, passages, roles | partial |
| guide_rods | features, passages, roles | partial |
| guide_sleeves | features, passages, roles | partial |
| lead_rod | features, passages, roles | partial |
| nut_block | features, passages, roles | partial |
| platform | features, passages, roles | partial |
| end_supports | features, passages, roles | partial |
| handwheel | features, passages, roles | partial |
| assembly_clearance | assembly, features, passages, roles | missing |
| topology | solid | complete |
| solid_validity | solid | complete |
| units | delivery | partial |
| hierarchy | editable | partial |
| materials | materials | missing |
| state_cycle | state | partial |
| glb_readable | delivery | complete |
| glb_assembled | delivery, state | partial |
| reconstruction | delivery, execution | partial |
| instructions | editable, execution | partial |
| procedural_materials | materials | partial |
| seed_quality | execution | partial |

### 方法输入、算法与输出

- `assembly`：在一次允许的整体坐标归一后，按关系测轴线距离、端面间隙、接触面和真实实体穿透；按每实例求最大空间偏差，不累加各零件合法公差。 输入：role_to_entities, world_feature_frames, public_relationships；输出：relationship_errors_mm, axis_angles_deg_diagnostic, contact_domains, signed_gap_intervals, penetration_evidence。无角色/完整表面证据时不可测；未指定角度阈值不自行新增硬门，孔位空间误差按公开公差。
- `cost`：记录全部成功失败和反馈轮次时间/token/工具/重试；未知token为null，成本不进入质量分。 输入：harness_attempt_ledger；输出：wall_seconds, token_usage_or_null, tool_calls, retries, per_round_cost。没有token观测则未知，不编造0；不因为成本未知提升/降低几何分。
- `delivery`：两格式各自采集真实世界几何，再比较尺度/姿态/孔槽/角色及可表达材质；约定米制与Z向上，交付元数据不能覆盖真实几何。 输入：independently_reopened_native_and_glb, source_units, artifact_manifest；输出：artifact_load_status, cross_format_geometry_material_errors, unit_orientation_evidence。格式/加载工具故障与候选缺产物区分；缺少等价阈值时保留诊断而非擅自放行。
- `editable`：实际部件可选择编辑、无重复/松散填料，关键参数可追溯到重建几何；不要求变量名、固定对象名或作者特征树。 输入：native_entities_and_hierarchy, source_rebuild_outputs；输出：editable_role_coverage, hierarchy_diagnostic, parameter_trace_evidence。参数可读性没有自动测量时单列辅助/人工，不用README存在冒充。
- `execution`：清洁目录、冻结公开输入和代码、禁私有GT及旧输出；由Harness管理执行超时重试/全seed，同一测量入口独立检查每次输出。 输入：harness_clean_runs, declared_public_inputs, source_and_artifact_hashes；输出：run_exit_and_receipts, dependency_access, seed_quality_reports, source_identity, readme_review。工具故障/超时与几何失败区分；不重试测到通过再挑最高分，不递归读取自身全seed总门。
- `features`：完整面域拟合平面/圆柱/圆弧/六角等，截面环分类内外边界，尺寸与形状残差分别输出；扫描全域或给保守覆盖界，不能用有限截面宣称全壁正确。 输入：matched_world_meshes, numeric_landmarks, full_requirement_text, case_blueprint；输出：feature_ids, face_domains, observed_intervals, error_intervals_mm, datum_evidence, representation_limits。特征表示不支持、闭环歧义或区间跨阈值时不可测；明确找到错误尺寸则失败。
- `materials`：位图/HDRI规则与材质正确性分开；取实际有效节点和逐面分配。Text按公开材质角色，Code相对初始；GLB仅比较可表达PBR，非恒定程序化等价不以diffuse_color代替。 输入：actual_used_material_graphs, face_assignments, world_lights_compositor, public_color_roles_or_initial_materials；输出：dependency_compliance, role_color_evidence, material_parameter_deltas, assignment_correspondence, format_limits。泛称蓝灰/金属未给唯一RGB或roughness时需公开pilot锚点，不能把私有作者数值做精确硬门。
- `passages`：检查完整三角面与连续孔道空域的相交/占用，并证明相邻空域存在开集交叠；检查独立通道的壁面邻接。盲孔另测实体底壁及禁止出口，不用几条射线证明连通。 输入：trusted_solid_meshes, expected_ports_and_relations, case_blueprint；输出：ports, certified_void_domains, connection_graph, blind_bottoms, forbidden_connections, obstruction_witnesses。实体可信性不足或预算/表示无法证明完整空域时不可测；缺预期出口、有封片或非法相通为失败。
- `review`：重渲染检查指定配色、特征可读性，供辅助诊断；不对Text使用未指定示意图像素排名，不用截图判断精确尺寸/孔道。 输入：trusted_native_review_renders, public_visual_requirements；输出：review_views, visible_feature_notes, unmeasured_semantics。整体文本语义/审美仍延期；不能冒充几何合同完成。
- `roles`：先以类型/尺度粗筛，再用真实截面/孔轴/相对关系作二分图匹配；同类对称置换等价。匹配残差不得通过逐件刚体配准消除；不能只凭AABB或对象名确定角色。 输入：trusted_world_meshes, public_role_counts, feature_and_relation_candidates；输出：role_to_entities, missing_roles, duplicate_roles, ambiguous_assignments, feature_evidence。不能可靠对应的角色相关测量不可测；匹配歧义如导致不同判定不能任选最高分。
- `solid`：逐交付实体检查流形、连通分量、退化面、法向、自交和正体积；合法语义零件可接触但不合并；统计只覆盖实际交付几何。 输入：trusted_world_meshes, declared_geometry_policy；输出：per_entity_validity, bad_edges_faces, components, signed_volume_m3。采集器失败/容量超限不可当候选无效；确定的非流形/自交等另给失败证据。
- `state`：逐件局部形状保持与帧1→61→1恢复分开；装配帧按题面关系测，爆炸帧检查部件可辨和保形，不复用装配接触门、不匹配作者爆炸坐标。 输入：single_session_native_state_sequence, persistent_entity_correspondence, glb_frame_1；输出：state_identity_map, shape_preservation_bounds, return_transform_error, state_material_results, readability_diagnostic。跟踪失配/未完成恢复不可测；不能用帧1和恢复一致推出中间帧保形。静态题不生成帧61要求。

### 执行与验收

- 装配数值仅帧1及返回帧1；帧61只保形/身份/材质/可辨，不强制装配接触；静态题无61
- 按实际资产/格式/状态去重作业，复用哈希绑定的角色/截面/完整面域；所有作业受同一父deadline和进程组回收约束
- 误差上界≤t通过；误差下界>t失败；跨阈值/缺证据/未支持表示不可测；参考/工具故障基础设施错误；不适用须提交前在规格中明示
- 相关回归、真实原生/GLB新候选、全部seed和独立复算均终态；保留失败及不可测，未经校准不启用新总分
- 待标定：颜色类别/金属观感数值锚点；未公开连续形状分归一化和角度阈值；跨格式程序化材质等价；参数可读性/爆炸可辨辅助评价；未支持表示和复杂装配预算性能。


明确数值条款、既有容差和当前检查覆盖见 JSON；既有代理检查不自动升级为完整方法。

## 评分

本题最终得分：`60% vlm + 30% data + 10% detail`。各分项定义与取证流程见[评分说明](../../../../../../../docs/cn/scoring.md)。

内容缺失、形状或布局偏差降低相应质量分；技术故障及必需证据缺失保留未完成状态，不能补零或重分配权重。交付、执行、加载、依赖及真实性按题目合同独立检查。评分采用绑定的真实场景重渲染证据，保留提交图片与不一致诊断。

数值检查仅覆盖已实现且有证据的指标，未实现的精确计数不视为达标。视觉判断不能证明隐藏几何、真实接触或完整物理正确性；参考区域和感知评分仍有校准限制。
