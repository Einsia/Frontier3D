#!/usr/bin/env python3
"""Check an explicitly supplied private provider configuration without exporting secrets."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", type=Path, required=True)
    p.add_argument("--model", default="gpt-5.6-sol")
    p.add_argument("--docker-image")
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    provider = json.loads(args.provider.read_text())
    if not provider.get("api_key") or not provider.get("base_url"):
        raise SystemExit("Provider configuration needs base_url and api_key")
    report = {"model": args.model, "docker_image": args.docker_image,
              "ready": False, "purpose": "connection_probe_not_benchmark_trial"}
    start = time.monotonic()
    env = dict(os.environ, L3_MODEL_API_KEY=provider["api_key"])
    container = "l3-model-probe-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="l3-model-") as tmp:
        home = Path(tmp)
        config = ('model = ' + json.dumps(args.model) + '\n'
                  'model_provider = "l3"\nmodel_reasoning_effort = "low"\n'
                  '[model_providers.l3]\nname = "Authorized L3 provider"\n'
                  'base_url = ' + json.dumps(provider["base_url"]) + '\n'
                  'wire_api = "responses"\nenv_key = "L3_MODEL_API_KEY"\n')
        (home / "config.toml").write_text(config)
        (home / "config.toml").chmod(0o600)
        inner_home = "/tmp/l3-codex" if args.docker_image else tmp
        common = ["exec", "--ephemeral", "--skip-git-repo-check",
                  "--output-last-message", inner_home + "/last.txt",
                  "Reply with exactly L3_MODEL_READY. Do not call tools."]
        if args.docker_image:
            # This is only a connection probe. Task networking needs a separate allowlist.
            report["image_id"] = subprocess.check_output(
                ["docker", "image", "inspect", args.docker_image, "--format", "{{.Id}}"],
                text=True).strip()
            command = ["docker", "run", "--rm", "--name", container,
                       "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                       "--cpus", "2", "--memory", "2g", "--pids-limit", "256",
                       "--user", f"{os.getuid()}:{os.getgid()}",
                       "--mount", f"type=bind,src={tmp},dst={inner_home}",
                       "-e", "L3_MODEL_API_KEY", "-e", "CODEX_HOME=" + inner_home,
                       "-e", "HOME=" + inner_home, "-w", inner_home,
                       "--entrypoint", "codex", args.docker_image,
                       common[0], "--dangerously-bypass-approvals-and-sandbox", *common[1:]]
        else:
            env["CODEX_HOME"] = tmp
            command = ["codex", common[0], "--sandbox", "read-only",
                       "-c", 'approval_policy="never"', *common[1:]]
        output = ""
        try:
            result = subprocess.run(command, cwd=tmp, env=env, capture_output=True,
                                    timeout=args.timeout)
            output = (result.stdout + result.stderr).decode(errors="replace")
            report["return_code"] = result.returncode
            final = home / "last.txt"
            report["ready"] = result.returncode == 0 and final.exists() and final.read_text().strip() == "L3_MODEL_READY"
        except subprocess.TimeoutExpired as error:
            output = ((error.stdout or b"") + (error.stderr or b"")).decode(errors="replace")
            report["timed_out"] = True
        finally:
            if args.docker_image:
                subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        lower = output.lower()
        if not report['ready']:
            errors=[line for line in output.splitlines() if line.startswith('ERROR:')]
            report['failure_detail']=(errors[-1] if errors else 'No structured CLI error line')[:1600].replace(provider['api_key'],'[REDACTED]')
        report["signals"] = {
            "authentication_error": any(t in lower for t in ("invalid api key", "401 unauthorized", "authentication failed")),
            "cloudflare_challenge": "cloudflare" in lower and ("just a moment" in lower or "challenge" in lower),
            "http_403": "403" in lower,
            "http_429": "429" in lower,
            "stream_disconnected": "stream disconnected" in lower,
        }
    report["elapsed_seconds"] = round(time.monotonic() - start, 2)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    raise SystemExit(0 if report["ready"] else 1)


if __name__ == "__main__":
    main()
