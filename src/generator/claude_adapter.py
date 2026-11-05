"""Claude Code bundle adapter, copied into each isolated generation attempt.

The parent owns retry/deadline/delivery validation. This adapter performs one
native invocation and preserves the native result and billable usage on failure.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--effort")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--allow-shell", action="store_true", help="Only enable inside a container with read-only task inputs")
    parser.add_argument("--image", type=Path, action="append", default=[])
    args = parser.parse_args()
    prompt = sys.stdin.read()
    if args.image:
        prompt += "\nRead each supplied reference image with the Read tool: " + ", ".join(map(str, args.image))
    env = dict(os.environ,
               ANTHROPIC_API_KEY=os.environ["CODEX_API_KEY"],
               ANTHROPIC_BASE_URL=args.base_url.rstrip("/").removesuffix("/v1"),
               CLAUDE_CONFIG_DIR=str(args.session / "claude"),
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
               ANTHROPIC_CUSTOM_MODEL_OPTION=args.model,
               ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES="effort,max_effort,thinking,adaptive_thinking")
    for name in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                 "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(name, None)
    tools = "Read,Glob,Grep,Bash" if args.allow_shell else "Read,Glob,Grep"
    command = [args.claude_bin, "-p", "--bare",
               "--model", args.model, "--output-format", "stream-json", "--verbose",
               "--setting-sources", "", "--permission-mode", "dontAsk",
               "--tools", tools, "--allowedTools", tools,
               "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
    if args.effort:
        command += ["--effort", args.effort]
    if args.schema:
        command += ["--json-schema", args.schema.read_text()]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=None, text=True, env=env, bufsize=1)
    process.stdin.write(prompt)
    process.stdin.close()
    final = None
    with (args.session / "claude-events.jsonl").open("w") as events:
        for line in process.stdout:
            events.write(line)
            events.flush()
            print(line, end="", flush=True)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "result":
                final = event
    code = process.wait()
    if final:
        usage = final.get("usage") or {}
        if "input_tokens" in usage and "output_tokens" in usage:
            print(json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": usage["input_tokens"] + usage.get("cache_read_input_tokens", 0) + usage.get("cache_creation_input_tokens", 0),
                "output_tokens": usage["output_tokens"],
                "cached_input_tokens": usage.get("cache_read_input_tokens"),
                "cache_write_input_tokens": usage.get("cache_creation_input_tokens"),
            }}), flush=True)
        if final.get("session_id"):
            print(json.dumps({"type": "thread.started", "thread_id": final["session_id"]}), flush=True)
    if code or not final or final.get("is_error"):
        raise RuntimeError("Claude Code did not deliver a successful native result; inspect retained events")
    value = final.get("structured_output")
    if value is not None:
        args.output.write_text(json.dumps(value))
    elif isinstance(final.get("result"), str) and final["result"].strip():
        args.output.write_text(final["result"])
    else:
        raise RuntimeError("Claude Code completed without a final submission")


if __name__ == "__main__":
    main()
