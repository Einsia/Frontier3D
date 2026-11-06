# 题目与汇总

[English](../en/tasks.md) · [文档导航](README.md)

当前发布集共**145题：L1 65题、L2 65题、L3 15题**。题包位于
[data/3dbench/tasks](../../data/3dbench/tasks)，全局编号为`3DBench-001`至`3DBench-145`。
L1/L2包含84道原生harness题和46道扩展题。

| 层级 | 类别 | 题数 |
| --- | --- | ---: |
| L1 | Text2Code | 15 |
| L1 | Image2Code | 25 |
| L1 | Image2Code-SingleView | 25 |
| L2 | Brief2Scene | 20 |
| L2 | Reference2Scene | 10 |
| L2 | Reference2Scene-RealPhoto | 25 |
| L2 | SceneEdit | 10 |
| L3 | Text2Environment | 5 |
| L3 | Image2Environment | 10 |

全部层级使用同一公开CLI：

~~~sh
python -m benchmark list
python -m benchmark run --task L1/Text2Code/task_L1_Text2Code_001 --output runs/check-l1
python -m benchmark run --task L3/Image2Environment/task_L3_Image2Environment_001 --output runs/check-l3
~~~

## L3题目身份

L3按公开`references.json/input_mode`分为5道文本题和10道图像题，共24张公开参考图；
独立冻结的评分参考集包含23项绑定。目录编号为`Text2Environment_001`—`005`和
`Image2Environment_001`—`010`，全局131—145保留原生`l3-e/g/r`执行key。
运行器接受公开ID和原生key。

[task-id-map.json](../../configs/release/task-id-map.json)记录原始ID，
[L3别名映射](../../configs/release/l3-input-category-map.json)显式解析旧Unified ID。
旧题身份不能仅按数字尾号推断。CodeEdit和PlayableGame题包不属于当前发布集。

## 成绩汇总

L1/L2使用`100 * S_core`，L3使用`score_100`。每层对全部题取算术平均，再计算：

~~~text
Total = 0.30 * L1 + 0.30 * L2 + 0.40 * L3
~~~

| 层级 | 必需成绩数 | 总分权重 | 单题总贡献 |
| --- | ---: | ---: | ---: |
| L1 | 65 | 30% | 0.461538% |
| L2 | 65 | 30% | 0.461538% |
| L3 | 15 | 40% | 2.666667% |

每层内各题等权。层级分要求该层全部题，总分要求145题齐全。缺测和技术无效测量保留缺失，
真实测得的0分及确认交付失败的0分参与汇总；缺题时不重新分配权重。成绩按模型与effort联合分组。

~~~sh
python -m benchmark summarize --scores /path/to/l12/scores.csv --scores /path/to/l3/scores.csv --output runs/combined
~~~

输出`leaderboard.csv`和`weighted-summary.json`，包含覆盖率、层级均分和加权贡献。
导入原始编号CSV时先过滤退役题，再显式使用`--identity source`。
切换已绑定的题集版本需创建新campaign。

机器定义见[汇总配置](../../configs/release/aggregation-policy.json)、
[题目集合](../../data/3dbench/tasks/collection.json)及[题目表](../reference/task-index.csv)。
