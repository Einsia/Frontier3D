# 文档导航

[English](../README.md)

安装、生成、渲染和测评统一使用[主README](../../README.md)中的
`python -m benchmark`命令。英文为默认版本，核心文档提供对应中文版。

| 文档 | 中文 | English |
| --- | --- | --- |
| 题目、编号与汇总 | [题目与汇总](tasks.md) | [Tasks](../en/tasks.md) |
| 模型与执行器 | [模型配置](models.md) | [Models](../en/models.md) |
| 预算、重试与恢复 | [实验设置](experiment.md) | [Experiments](../en/experiment.md) |
| 计分与部分分 | [评分规则](scoring.md) | [Scoring](../en/scoring.md) |
| 输出文件与导出 | [结果与导出](results.md) | [Results](../en/results.md) |
| 题目资产许可 | [资产许可](licenses.md) | [Licenses](../en/licenses.md) |

[分项算法](../en/reference/metrics.md)和[L3 UE评分](../en/reference/l3.md)提供英文技术细节。
机器可读的题目、评分和署名索引集中在[reference目录](../reference/README.md)。

## 运行要求

| 范围 | 依赖 |
| --- | --- |
| 全部层级 | Linux x86-64、Python 3.13、Node.js 22+、Git LFS、Docker、所选模型CLI及服务 |
| L1/L2 | Blender 5.2.1及候选执行Docker镜像 |
| L3 | 已获许可的UE 5.8.3、分别可写的候选和测评引擎副本、NVIDIA/Vulkan、外部CLI目录及校验后的素材库 |

命令见[安装说明](../../README.md#install)和[L3配置](../../README.md#configure-l3-ue)。
各执行器的API要求见[模型配置](models.md)。未知候选使用Docker运行；
本机执行使用宿主机权限，详见[安全说明](../../SECURITY.md)。

## 检查安装

~~~sh
python -m benchmark doctor --resources-only
python scripts/verify_release.py
python -m benchmark doctor
~~~

资源检查无需模型服务。完整doctor检查可执行文件、版本和宿主配置，不调用模型或启动UE。
全量运行前先用单题确认提供方和GPU可用。离线测试覆盖代码行为；
全部145题在每种提供方和宿主环境中在线生成并测评，仍需实际运行确认。
