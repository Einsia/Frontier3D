# 评分规则

[English](../en/scoring.md) · [文档导航](README.md)

全部层级使用`python -m benchmark run/generate/evaluate`。最终单题报告位于`main_results/<model>/<task>/report.json`，`S_core`范围为`[0,1]`，乘100得到百分制。层级均分及30/30/40总分见[题目与汇总](tasks.md)。

## 测评流程

1. 生成源码并按公开合同验证交付。修复反馈包含公开执行错误，不包含私有评分反馈。
2. 固定已接受源码和生成记录，测评使用同一候选。调用者提供的源码以`provided_source`标记。
3. 隔离执行并采集场景、必需图像、导出、依赖和执行seed。L3对冻结UE工程独立构建、渲染和回放。
4. 按配置测量原生、图像、视觉裁判和detail分项。L1/L2包含84道原生harness题、46道扩展题。
5. 校验源码、规则、参考、产物及裁判绑定，汇总完整测量并导出报告。

`run --all`逐题生成并测评；`generate --all`后接`evaluate --all --resume`可先完成全部生成。中间原生报告、`S_vlm`和screening分数各有用途，单题最终成绩读取最终报告。

## 题内权重

| 任务家族 | 最终公式 |
| --- | --- |
| Text2Code、Brief2Scene | `0.60 vlm + 0.30 data + 0.10 detail` |
| Image2Code、SingleView、Reference2Scene、RealPhoto | `0.50 main_image + 0.20 localization + 0.20 vlm + 0.10 detail` |
| SceneEdit | `0.20 numeric + 0.30 target + 0.20 preservation + 0.20 vlm + 0.10 detail` |
| L3环境题 | `0.60 visual_quality + 0.20 task_fidelity + 0.05 layout + 0.15 interaction` |

| 分项 | 测量内容 |
| --- | --- |
| `data`、`numeric` | 逐题几何、数量、参数及已实现内容检查；扩展Brief有agent辅助的原生测量核验 |
| `main_image` | 固定参考图外观算法；下列四题专项使用视觉结构判断 |
| `localization` | 冻结参考对象框、VLM候选观测及确定性配对 |
| `target`、`preservation` | 原生几何或照明检查测量目标编辑和未修改内容 |
| `vlm` | 冻结语义、参考保真、编辑或美学rubric |
| `detail` | 局部形态与零件组合检查；一题还含原生机构运动测量 |

详细公式见英文[算法参考](../en/reference/metrics.md)及[L3评分](../en/reference/l3.md)。逐题定义见[L1/L2清单](../reference/scoring-task-inventory.json)、[原生规则](../../configs/release/linear-config)、[扩展规则](../../configs/release/addition-config)及[L3细则](../../harness/L3/release/scoring-specs/manifest.json)。

## Detail变体

最终L1/L2组合将基线中的10%接触／支撑分项替换为detail，其余分项与权重保留。原测量留在报告替换记录中，执行、加载、依赖和材质合法性检查继续适用。

对冻结原子集合`C`和必需变体集合`P`：

~~~text
w'_i = w_i / sum(w_j for j in C)
q_(v,i) = coverage_(v,i) * (1 - deviation_(v,i))
D_v = sum(w'_i * q_(v,i) for i in C)
D = min(D_v for v in P)
~~~

先求每个变体完整detail分，再选最小变体；全部原子取自同一选中变体。必需项技术缺测会阻塞结果；已确认的候选缺陷可按明确政策记录局部零分。

- 45道原生L1通常使用primary及3个seed，各含native／GLB，共8个变体。
- 39道原生L2通常使用primary及3个seed，共4个native变体，实际seed ID以逐题合同为准。
- 扩展题通常对应L1的8个或L2的4个变体。
- `detail-only-v1`只缩小单次裁判的计分原子清单，保留定义与权重，不缩减变体总体。

公开CLI使用完整冻结总体。底层screening及变体数量开关可产生诊断子集；比较成绩前检查`required_variants`和`measured_variants`。

## 四题专项

四道原生题采用`direct-components-linear-r2`，按下表的线性视觉观察生成最终`main_image`、`vlm`及`detail`；保留基线`localization`和50/20/20/10系数。

| 题目 | `main_image` | `vlm` | `detail` |
| --- | --- | --- | --- |
| SingleView_001，鞋 | `0.50 shoe_profile + 0.50 shoe_upper` | `shoe_laces` | `shoe_sole` |
| SingleView_009，马头 | `2/3 horse_profile + 1/3 horse_neck` | `horse_anatomy` | `horse_mane` |
| SingleView_010，大卫胸像 | `0.70 david_face + 0.30 david_bust` | `david_surface` | `david_hair` |
| Reference2Scene-005，城市 | `0.50 city_layout + 0.50 city_buildings` | `city_facades` | `city_roofs` |

每个原子使用`coverage * (1 - deviation)`。专项对已绑定的基线候选判断，不套用普通detail的8／4变体最小值。清单中的`final_override`标记该例外，实现见[legacy_detail_v2.py](../../src/evaluator/legacy_detail_v2.py)。

## 有效性与部分分

| 结果 | 计分处理 |
| --- | --- |
| 已测内容缺陷、比例错误、必需细节缺失或曝光差 | 相关质量项低分／零分，保留其他已测项和固定权重 |
| 确认违反交付合同，如场景无法加载、依赖被禁止 | 可出现`score_valid=false`、`system_invalid`和`S_core=0`，需查看具体gate |
| API故障、技术证据损坏／缺失、绑定不符、测量未实现 | 保留缺测（`S_core=null`或`technical_failure`）和证据 |
| 签名、seed或提交图片差异 | 记录诊断，并按该路由的证据策略处理 |

交付检查包括实际执行、必需文件、场景／GLB加载、可编辑几何、图像尺寸、依赖及全部必需seed。系统检查通过不代表语义质量达标。

绑定保存场景的重渲染成功后，基线和detail可读取该权威图像，原提交PNG及差异保留为诊断。重渲染沿用题目的相机、帧和呈现策略，不修复候选照明或曝光。seed几何差异与已确认的执行／加载失败分别处理；缺少seed证据仍需解决。

参考贴图检查追踪活动材质、世界与合成节点、打包图像哈希和UV覆盖，区分仅存储参考图与实际渲染使用。完整参考画面贴到简单平面违反建模合同。题面允许的局部裁切需节点／UV证据支持；大范围、缠绕或不明确的使用需复核。

[候选异常政策](../../configs/evaluation/candidate-robustness-v1.json)仅允许将已确认由候选内容导致不可定义的受影响检查记零，排除API、文件系统、来源不符及基础设施中断。未知崩溃需诊断，保留原测量快照与恢复原因。

每个正权重分项都需有限测量。技术缺测不填零，缺失detail权重不重分配，裁判重试不按分数择优。扩展Brief仅对`satisfied`条目给分，分母固定为`native_content_checks`总体；其他已接受状态保留在分母和未决列表。核验失败或未绑定时仍阻塞输出。

## 示例与解释

普通参考题交付有效，图像为`0.60`、定位`0.50`、VLM `0.75`、detail `0.40`时：

~~~text
S_core = 0.50*0.60 + 0.20*0.50 + 0.20*0.75 + 0.10*0.40 = 0.59
~~~

即59／100。必需detail判断缺失时总分缺测；实际测得的特征缺失可正常记零。

定位主要测量二维对象布局，RealPhoto没有统一的原生三维真值。参考区域、感知权重与AI判断仍有校准限制。报告中的`formal_score_eligible`、`human_calibrated`和`limitations`字段继续有效。结合分项证据解释总分，详见[结果说明](results.md)。
