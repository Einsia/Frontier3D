# L3 UE 开发容器

该目录提供 UE 5.8.3 源码引擎所需的 Linux 依赖镜像和公开开发工具。它是 Harbor 环境接入所需的组件；完整 trial 还需要模型认证、模型端点网络白名单、独立引擎副本、预算控制、产物冻结和私有 verifier。

## 镜像与资源

在拥有 `3dbench-codex:0.163.0` 的主机执行：

```sh
docker build -t 3dbench-l3-agent:ue5.8.3-codex0.163.0 \
  -f ue5/agent_environment/Dockerfile ue5/agent_environment
```

部署记录必须保存基础镜像和输出镜像的 image ID。Dockerfile 的 apt 安装用于准备环境；正式实验使用已构建镜像的固定 ID，不在 trial 内重新安装依赖。引擎、素材和模型凭据不包含在该依赖镜像中。UID/GID 默认为服务器上的 `20018:20018`，其他环境须显式配置 build args。

每次 trial 使用独立 workspace 和独立的源码引擎副本。源码引擎的项目编译会写入 Engine/Binaries、Intermediate 等位置，因此不能向多个 agent 暴露同一份可写引擎。可在计时前使用独立复制或真正的写时复制快照；禁止硬链接共享可写文件。容器内的 `UE5_ROOT` 保留引擎构建时的绝对路径，以兼容构建缓存；该路径挂载的是 trial 副本。组织方的标准引擎用于独立重建，不依赖 agent 修改后的引擎。

推荐容器边界：非 root、`--cap-drop ALL`、`--security-opt no-new-privileges`、明确 CPU/内存/进程上限，只暴露一张指定 GPU。不挂载宿主 Docker socket、用户 home、SSH 配置、仓库根目录或历史候选。公共输入和素材只读，workspace 与本次引擎副本可写。健康检查及候选评测采用 `--network none`；模型运行的网络须单独配置端点白名单，不能直接沿用断网配置。

## 公共文件

组织方将下列文件复制到单独目录后，只读挂载到 `/opt/l3-public`：

- 本目录的 `ue.py`。
- 本目录的 `ASSETS.md`，同时作为任务公共输入提供。
- `ue5/BenchRuntime/` 接口与观察器源码。
- `tools/ue_import_l3_materials.py` 素材导入器。

素材目录分别挂载到 `/assets/polyhaven` 和 `/assets/kenney`，包含 manifest、来源许可和纹理文件。仅提供这些公开文件，不挂载 harness 私有计划和评分代码。模型可以直接调用 UE、自写脚本，也可以使用公开 helper；helper 的结果仅供开发反馈，不是评分依据。

## 编译与预览

设置 `UE5_ROOT`、可写 `HOME` 和 `UE_LocalDataCachePath`。项目放在 `/workspace/project`。以下命令在容器内部执行：

```sh
# 新项目安装公共接口；已有接口时须先检查，不自动覆盖。
python3 /opt/l3-public/ue.py install-interface /workspace/project

# 每次使用新的输出目录，保留编译诊断。
python3 /opt/l3-public/ue.py build /workspace/project \
  --output /workspace/checks/build-001 --jobs 16 --timeout 1800

# 相机位置与目标由 agent 自选，单位厘米。
python3 /opt/l3-public/ue.py preview /workspace/project \
  --output /workspace/checks/view-001 \
  --position -11000 -13000 11000 --target 0 0 0 --timeout 1800

# agent 可自行编写公开观察器支持的动作序列并检查结果。
python3 /opt/l3-public/ue.py preview /workspace/project \
  --output /workspace/checks/action-001 --plan /workspace/my-actions.json
```

`build` 运行 C++ 构建和 CompileAllBlueprints（包括启用的插件）。没有唯一 `*Editor.Target.cs` 时，显式提供 `--editor-target`。`preview` 运行 Vulkan 离屏渲染，验证观察器结束标记和每个 capture 的 PNG 输出。截图由 agent 自行查看；命令退出成功不代表视觉正确或交互通过。每条引擎命令有超时，完整 trial 的墙钟预算由外部运行器控制。共享文件系统上的缓存使用 `NoZenLocalFallback`，避免 Zen 数据库锁依赖。

自写计划示例：

```json
{
  "version": 1,
  "kind": "development_preview",
  "steps": [
    {"op": "camera", "name": "camera", "position_cm": [-11000, -13000, 11000], "target_cm": [0, 0, 0]},
    {"op": "wait", "name": "settle", "seconds": 2},
    {"op": "capture", "name": "overview"}
  ]
}
```

交互计划可使用公共观察器的 `fixture`、`look`、`interact`、`wait`、`snapshot` 等操作。开发反馈允许暴露运行时状态；隐藏评测路线、参考标注和评分结果不得进入 workspace。

## 环境证据

模型连通性探针在宿主机运行。配置文件包含 `base_url`（Responses API 的 `/v1` 前缀）和 `api_key`，保存在仓库外、权限 `0600`。不把密钥放在命令行参数中：

```sh
python3 tools/probe_l3_model.py \
  --provider "$HOME/.config/3dbench/provider.json" \
  --docker-image 3dbench-l3-agent:ue5.8.3-codex0.163.0 \
  --output data/l3/docker-environment/model-probe.json
```

探针只记录连接结果与镜像 ID，不保存凭据或原始请求日志。临时容器仅挂载自己的临时 Codex 配置；它用普通网络验证推理服务，不能代替正式 trial 的端点白名单检查。实际 Responses 调用与 `/models` 列表接口分别判断，后者被网关拦截不意味着前者不可用。

服务器健康检查位于 `data/l3/docker-environment/`。工程样例来自 `data/l3/minecraft/integration-submission/project`，带有人工兼容性修补，只能用于基础设施验证，不是自主生成提交。该样例的缓存可用于同一样例的环境检查，不能作为跨候选、跨模型复用的正式生成缓存。
