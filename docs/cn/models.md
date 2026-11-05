# 模型与执行器

[English](../en/models.md) · [文档导航](README.md)

[模型配置](../../configs/release/model-harness-contract.json)统一规定每个模型在
**L1/L2/L3**使用的原生执行器与生成effort。CLI包名和固定版本见
[generator-harnesses.json](../../configs/release/generator-harnesses.json)。

| 模型 | 执行器 | Effort |
| --- | --- | --- |
| gpt-6-astra | Codex | max |
| gpt-6.1-sol | Codex | max |
| gpt-6-luna | Codex | max |
| claude-opus-5-5 | ClaudeCode | max |
| gemini-3.1-pro-preview | gemini-cli | high |
| glm-5.3-flash | zcode | max |
| qwen3.8-max | ClaudeCode | xhigh |
| kimi-k3 | Kimi codecli | max |
| kimi-k3.1-pro | Kimi codecli | max |
| deepseek-v4.1-flash | DeepSeek Harness | max |
| MiniMax-M3.1-Flash | ClaudeCode | max |
| doubao-seed-evolving | ClaudeCode | max |

省略`--effort`时使用表内值；对已列出的模型，显式指定不一致的effort会被拒绝。
请求使用实际提供方模型ID，harness名称用于标识工具运行时。
Claude的规范ID为`claude-opus-5-5`。自定义模型需提供兼容配置并记录真实身份。

## 提供方API

| 执行器 | 所需API |
| --- | --- |
| Codex | Responses |
| ClaudeCode | Anthropic Messages，含工具和题目所需图像输入 |
| DeepSeek Harness、Kimi codecli、zcode | 与所选CLI兼容的Chat Completions |
| gemini-cli | 原生Gemini `v1beta/models` |

OpenAI兼容端点可能只支持其中部分API。生成使用`OPENAI_MODEL`、`OPENAI_BASE_URL`和
`OPENAI_API_KEY`；不同harness沿用这些变量名。独立裁判使用`VLM_*`。
指定env文件中的提供方配置优先于继承的环境变量。

Claude、Qwen、MiniMax和Doubao使用Claude Code 2.1.268。适配器会去除Messages基址
末尾的`/v1`。本机可用`GENERATOR_CLAUDE_BIN`指定CLI，Docker使用
`GENERATOR_CLAUDE_DOCKER_IMAGE`。L3把所选CLI安装到外部`L3_NATIVE_CLI`目录。
安装命令及其他覆盖项见[安装说明](../installation.md#install)。

## 运行选项

按[安装与运行指南](../installation.md#model-harnesses)中的固定版本安装所选CLI。本机可执行文件覆盖项为：

| Harness ID | 可执行文件变量 |
| --- | --- |
| codex | `GENERATOR_CODEX_BIN` |
| claude-code | `GENERATOR_CLAUDE_BIN` |
| zcode | `GENERATOR_ZCODE_BIN` |
| kimi-codecli | `GENERATOR_KIMI_BIN` |
| deepseek-harness | `GENERATOR_DSH_BIN` |
| gemini-cli | `GENERATOR_GEMINI_BIN` |

`GENERATOR_RUNTIME`可选`local`或`docker`。Docker镜像覆盖项为：Codex使用`GENERATOR_DOCKER_IMAGE`，Claude Code使用`GENERATOR_CLAUDE_DOCKER_IMAGE`，其他CLI使用`GENERATOR_NATIVE_DOCKER_IMAGE`。本机Claude Code提供Read／Glob／Grep，Docker还提供Bash，并以只读任务工作区检查二进制输入。

L3将所选包安装到`L3_NATIVE_CLI`目录，候选使用占位令牌与宿主网关通信，提供方凭据保留在宿主机。

## 裁判配置

固定独立裁判为`gpt-6-astra`、**medium** effort。部分compact适配器在代码中指定该身份，
单独更改`VLM_MODEL`无法切换整条评分链路，详见[裁判配置](results.md#裁判配置)。

模型、effort或harness变化时创建新campaign。已有产物保留原始身份，
不同effort的成绩分别汇总。`doctor --model MODEL`只检查所选CLI；
提供方是否在线可用需通过单题运行确认。
