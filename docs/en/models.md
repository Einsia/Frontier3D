# Models and harnesses

[中文](../cn/models.md) · [Documentation](../README.md)

The [model contract](../../configs/release/model-harness-contract.json) binds
each model to its native harness and generation effort on **L1/L2/L3**.
CLI packages and pinned versions are in
[generator-harnesses.json](../../configs/release/generator-harnesses.json).

| Model | Harness | Effort |
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

Omit `--effort` to use the table value. A conflicting explicit effort is
rejected for listed models. Use the actual provider model ID; a harness name
identifies the tool runtime. The canonical Claude ID is `claude-opus-5-5`.
Custom models need a compatible configuration and a recorded identity.

## Provider APIs

| Harness | Required API |
| --- | --- |
| Codex | Responses |
| ClaudeCode | Anthropic Messages, including tools and required images |
| DeepSeek Harness, Kimi codecli, zcode | Chat Completions compatible with the selected CLI |
| gemini-cli | Native Gemini `v1beta/models` |

An OpenAI-compatible endpoint may support only some of these APIs. Generation
uses `OPENAI_MODEL`, `OPENAI_BASE_URL` and `OPENAI_API_KEY`; these variable names
are retained across harnesses. `VLM_*` configures the independent judge. Provider
values in the selected env file override inherited provider settings.

Claude, Qwen, MiniMax and Doubao use Claude Code 2.1.268. The adapter removes
a trailing `/v1` from the Messages base URL. Host overrides include
`GENERATOR_CLAUDE_BIN`; Docker uses `GENERATOR_CLAUDE_DOCKER_IMAGE`. L3 installs
the selected CLI in the external `L3_NATIVE_CLI` prefix. Installation and other
executable overrides are in the [setup guide](../../README.md#install).

## Runtime options

Install only the selected CLI using the pinned packages in the [main README](../../README.md#model-harnesses). Host executable overrides are:

| Harness ID | Executable variable |
| --- | --- |
| codex | `GENERATOR_CODEX_BIN` |
| claude-code | `GENERATOR_CLAUDE_BIN` |
| zcode | `GENERATOR_ZCODE_BIN` |
| kimi-codecli | `GENERATOR_KIMI_BIN` |
| deepseek-harness | `GENERATOR_DSH_BIN` |
| gemini-cli | `GENERATOR_GEMINI_BIN` |

Set `GENERATOR_RUNTIME=local` or `docker`. Docker image overrides are `GENERATOR_DOCKER_IMAGE` for Codex, `GENERATOR_CLAUDE_DOCKER_IMAGE` for Claude Code and `GENERATOR_NATIVE_DOCKER_IMAGE` for the other CLIs. Local Claude Code exposes Read/Glob/Grep; Docker also exposes Bash with a read-only task workspace for inspecting binary inputs.

For L3, install the selected package under `L3_NATIVE_CLI`; the candidate talks to the host gateway with a placeholder token, while provider credentials stay on the host.

## Judge and campaign identity

The fixed judge is `gpt-6-astra` at **medium** effort. Some compact adapters
set that identity in code; changing `VLM_MODEL` alone does not switch the whole
scoring pipeline. See [judge configuration](results.md#judge-configuration).

Changing model, effort or harness requires a fresh campaign. Existing outputs
retain their original identities. Scores from different efforts are grouped
separately. `doctor --model MODEL` checks the selected CLI without provider calls;
online availability needs an actual task run.
