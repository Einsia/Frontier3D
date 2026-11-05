# L3 UE harness

L3 通过根目录的 `python -m benchmark` 统一入口运行，使用主 `.env` 的 `L3_*` 配置。
安装、资产准备、生成、独立 UE 采集和 v5 测评见[安装与运行指南](../../../../../../docs/installation.md#configure-l3-ue)。

本目录保留 UE 场景、交互、提交冻结校验和评分实现；L1/L2 继续使用对应的 Blender 检查。
当前活动任务由 `harness/L3/release/task-index.json` 及 `data/3dbench/tasks/L3/Unified/` 定义。
