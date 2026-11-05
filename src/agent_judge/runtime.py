"""Fresh Codex home and workspace sandbox for each attempt.

Only authentication/provider settings are inherited; never MCP, hooks, skills,
user instructions, candidate model names, or previous scores.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import venv
from contextlib import contextmanager
from pathlib import Path

import tomllib

from .protocol import digest, read_json, write_json
from src.run_usage import parse_events,with_archived_usage


def frozen_blender_worker(expected_sha256, attempt, current_source=None):
    """Snapshot the worker version named by this packet, including old retries."""
    if not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256):
        raise ValueError('Interactive packet has no valid frozen Blender worker SHA256')
    current_source = Path(current_source) if current_source is not None else Path(__file__).with_name('blender_worker.py')
    attempt = Path(attempt)
    owner = attempt.parent.resolve()
    candidates = [current_source]
    # An operator may archive failed attempts while the retained packet still
    # names their worker version. Keep that exact version beside the stage;
    # never substitute the current worker for a frozen packet.
    candidates.append(attempt.parent/'frozen-workers'/(expected_sha256+'.py'))
    candidates.extend(sorted(attempt.parent.glob('attempt-*/renderer/blender_worker.py')))
    for index, candidate in enumerate(candidates):
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if index and not candidate.resolve().is_relative_to(owner):
            continue
        data = candidate.read_bytes()
        if hashlib.sha256(data).hexdigest() == expected_sha256:
            return data, {'expected_sha256': expected_sha256, 'selected_source': str(candidate.resolve()),
                          'selected_sha256': expected_sha256}
    raise ValueError('No trusted Blender worker matches frozen packet SHA256 '+expected_sha256)


def archive_sessions(home,attempt,secrets):
    """Retain only rollout JSONL; credentials and provider configuration stay temporary."""
    source=home/'sessions';saved=[]
    if source.is_dir():
        for file in source.rglob('*.jsonl'):
            if file.is_symlink() or not file.is_file() or not file.resolve().is_relative_to(source.resolve()):continue
            target=attempt/'sessions'/file.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(redact(file.read_text(encoding='utf-8',errors='replace'),secrets),encoding='utf-8')
            saved.append({'path':str(target.relative_to(attempt)),'sha256':digest(target)})
    write_json(attempt/'session_archive.json',{'files':saved,'credentials_included':False,
        'isolated_attempt':True,'rollout_retained':bool(saved)})


@contextmanager
def evidence_workspace(private_temp):
    # Python 3.13 creates TemporaryDirectory with a Windows owner-only ACL.
    # The restricted Codex token cannot traverse that parent. Keep credentials
    # there, but put non-secret evidence in a sibling with normal inherited ACLs.
    private = Path(private_temp).resolve()
    work = private.with_name(private.name + "-workspace")
    work.mkdir(mode=0o755, exist_ok=False)
    try:
        yield work
    finally:
        resolved = work.resolve()
        if (
            resolved.parent != private.parent
            or resolved.name != private.name + "-workspace"
        ):
            raise RuntimeError("Refusing cleanup outside the owned temporary workspace")
        shutil.rmtree(resolved)


def terminate(process):
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def invoke(command, *, cwd, env, prompt, timeout):
    kwargs = {"start_new_session": True} if os.name != "nt" else {}
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kwargs,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate(process)
        stdout, stderr = process.communicate()
    return {
        "returncode": process.returncode,
        "timed_out": timed_out,
        "seconds": round(time.monotonic() - started, 3),
        "stdout": stdout,
        "stderr": stderr,
    }


def auth_environment(home: Path, source: Path):
    """Return minimal env/config and secret values to redact; secrets stay temporary."""
    source = source.expanduser().resolve()
    config_path = source / "config.toml"
    config = (
        tomllib.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {}
    )
    provider_id = config.get("model_provider", "openai")
    provider = config.get("model_providers", {}).get(provider_id)
    allowed = {
        "name",
        "base_url",
        "wire_api",
        "env_key",
        "requires_openai_auth",
        "http_headers",
        "env_http_headers",
        "query_params",
    }
    provider = {k: v for k, v in (provider or {}).items() if k in allowed}
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "PROGRAMDATA",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "NO_PROXY",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "LANG",
            "LC_ALL",
        }
    }
    secrets = []
    keys = {"OPENAI_API_KEY", "CODEX_API_KEY", provider.get("env_key")}
    keys.update(provider.get("env_http_headers", {}).values())
    for key in keys - {None}:
        if os.environ.get(key):
            env[key] = os.environ[key]
            secrets.append(os.environ[key])
    if (source / "auth.json").is_file():
        auth = read_json(source / "auth.json")
        write_json(home / "auth.json", auth)
        os.chmod(home / "auth.json", 0o600)

        def collect(value):
            if isinstance(value, str) and len(value) > 12:
                secrets.append(value)
            elif isinstance(value, dict):
                for v in value.values():
                    collect(v)

        collect(auth)
    if provider:
        lines = [
            f"model_provider = {json.dumps(provider_id)}",
            f"[model_providers.{json.dumps(provider_id)}]",
        ]
        for key, value in provider.items():
            if isinstance(value, dict):
                encoded = (
                    "{ "
                    + ", ".join(
                        f"{json.dumps(k)} = {json.dumps(v)}" for k, v in value.items()
                    )
                    + " }"
                )
                if key == "http_headers":
                    secrets.extend(value.values())
            else:
                encoded = json.dumps(value)
            lines.append(f"{key} = {encoded}")
        (home / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env["CODEX_HOME"] = str(home)
    env["PYTHONUTF8"] = "1"
    return env, secrets


def redact(value, secrets):
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret:
            value = value.replace(secret, "<redacted>")
    return re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1<redacted>", value)


def run_codex(
    packet: Path,
    attempt: Path,
    *,
    model,
    effort,
    codex,
    codex_home,
    timeout,
    runtime="local",
    docker_image="3dbench-agent-judge:local",
    blender=None,
    render_timeout=90,
    api_key=None,
    retry_feedback=None,
    measurement_catalogue=None,
    image_transport="original",
    engine="codex",
    responses_options=None,
    inspection_guidance=None,
):
    if engine not in {'codex', 'responses'} or engine == 'responses' and runtime != 'local':
        raise ValueError('Unsupported judge execution engine')
    attempt.mkdir(parents=True, exist_ok=False)
    with (
        tempfile.TemporaryDirectory(prefix="3dbench-judge-") as temp,
        evidence_workspace(temp) as work,
    ):
        temp = Path(temp)
        home = temp / "home"
        home.mkdir(mode=0o700)
        shutil.copytree(packet, work, dirs_exist_ok=True)
        env, secrets = auth_environment(home, codex_home)
        if api_key:
            # The caller's explicit provider credentials win over inherited
            # process keys; do not mutate os.environ across concurrent judges.
            env['OPENAI_API_KEY'] = api_key
            env['CODEX_API_KEY'] = api_key
            secrets.append(api_key)
        # Responses uses only trusted tool brokers launched with sys.executable;
        # it never exposes a model shell that needs a private Python environment.
        if runtime == "local" and engine == "codex":
            venv.EnvBuilder(with_pip=False).create(work / ".venv")
            scripts = work / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
            env["VIRTUAL_ENV"] = str(work / ".venv")
        root = str(work) if runtime == "local" else "/workspace"
        packet_manifest = read_json(packet / "manifest.json")
        interactive = packet_manifest["mode"] == "interactive"
        if interactive:
            if not blender:
                raise ValueError("Interactive mode requires a Blender executable")
            # Separate immutable input snapshot, trusted code and ledger from model files.
            private = home / "blender"
            private.mkdir()
            for role in ("candidate", "reference"):
                shutil.copytree(packet / role, private / "inputs" / role)
            worker_bytes, worker_version = frozen_blender_worker(
                packet_manifest['interactive_worker_sha256'], attempt)
            (private/'blender_worker.py').write_bytes(worker_bytes)
            write_json(private/'worker-version.json', worker_version)
            for name in ("blender_tools.py", "image_codec.py"):
                shutil.copyfile(Path(__file__).with_name(name), private / name)
            private_root = str(private) if runtime == "local" else "/codex-home/blender"
            settings = {
                "private": private_root,
                "workspace": root,
                "blender": blender,
                "worker": f"{private_root}/blender_worker.py",
                "timeout": render_timeout,
                "budget": packet_manifest["tool_budget"],
                "image_transport": image_transport,
                "scenes": {
                    p: s
                    for p, s in packet_manifest["sha256"].items()
                    if p.lower().endswith(".blend")
                },
            }
            write_json(private / "config.json", settings)
            executable = (
                sys.executable if runtime == "local" else "/opt/judge-venv/bin/python"
            )
            with (home / "config.toml").open("a", encoding="utf-8") as stream:
                stream.write("\n[mcp_servers.judge_blender]\n")
                stream.write(f"command = {json.dumps(executable)}\n")
                stream.write(
                    "args = "
                    + json.dumps(
                        [
                            f"{private_root}/blender_tools.py",
                            f"{private_root}/config.json",
                        ]
                    )
                    + "\n"
                )
                stream.write(
                    f"tool_timeout_sec = {render_timeout + 15}\nstartup_timeout_sec = 20\nrequired = true\n"
                )
        measurements = None
        if measurement_catalogue is not None:
            if runtime != 'local':
                raise ValueError('Bound native measurements currently require local judge runtime')
            source = Path(measurement_catalogue['path']).resolve(strict=True)
            if digest(source) != measurement_catalogue['sha256']:
                raise ValueError('Native measurement catalogue changed')
            measurements = home / 'native-measurements'
            measurements.mkdir()
            for source_file in (Path(__file__).with_name('native_measurements.py'),
                                Path(__file__).parents[1] / 'evaluator/l2_triangle_contact.py'):
                shutil.copyfile(source_file, measurements / source_file.name)
            write_json(measurements / 'config.json', {
                'catalogue': measurement_catalogue, 'workspace': str(work),
                'output': str(measurements / 'generated'), 'budget': 100,
            })
            with (home / 'config.toml').open('a', encoding='utf-8') as stream:
                stream.write('\n[mcp_servers.native_geometry]\n')
                stream.write('command = ' + json.dumps(sys.executable) + '\n')
                stream.write('args = ' + json.dumps([str(measurements / 'native_measurements.py'), str(measurements / 'config.json')]) + '\n')
                stream.write('tool_timeout_sec = 180\nstartup_timeout_sec = 20\nrequired = true\n')
        command = [
            codex if runtime == "local" else "codex",
            "exec",
            "-",
            "--model",
            model,
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--cd",
            root,
            "--json",
            "--config",
            'approval_policy="never"',
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--config",
            "sandbox_workspace_write.network_access=false",
            "--output-schema",
            f"{root}/response.schema.json",
            "--output-last-message",
            f"{root}/response.json",
        ]
        if os.name == "nt" and runtime == "local":
            command.extend(["--config", 'windows.sandbox="unelevated"'])
        from .image_transport import prepare_images
        attached_images,transport_record=prepare_images(work,attempt,packet_manifest,image_transport)
        for relative in attached_images:
            command.extend(["--image", f"{root}/{relative}"])
        container = "judge-" + temp.name
        if runtime == "docker":
            # Only this attempt's copies/auth are mounted. No Docker socket/host repo.
            prefix = [
                "docker",
                "run",
                "-i",
                "--rm",
                "--name",
                container,
                "--init",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=128",
                "--memory=4g",
                "--cpus=2",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,size=512m",
                "-v",
                f"{work}:/workspace",
                "-v",
                f"{home}:/codex-home",
                "-e",
                "CODEX_HOME=/codex-home",
                "-e",
                "HOME=/tmp",
                "-w",
                "/workspace",
            ]
            # API secrets travel through inherited env, never CLI arguments.
            if os.name != 'nt':
                prefix.extend(['--user',f'{os.getuid()}:{os.getgid()}'])
            for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
                if key in env:
                    prefix.extend(["-e", key])
            # Provider-specific environment keys are also supported.
            config = (
                tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
                if (home / "config.toml").exists()
                else {}
            )
            for provider in config.get("model_providers", {}).values():
                for key in [
                    provider.get("env_key"),
                    *provider.get("env_http_headers", {}).values(),
                ]:
                    if key and key in env:
                        prefix.extend(["-e", key])
            command = [*prefix, docker_image, *command]
        prompt = (packet / "prompt.txt").read_text(encoding="utf-8")
        if inspection_guidance:
            prompt += '\nDIAGNOSTIC VIEW POLICY:\n' + inspection_guidance + '\n'
        if retry_feedback:
            prompt += "\nThe preceding attempt failed technical validation (not a quality-score rejection). Repair every reported error without changing the rubric: " + str(retry_feedback) + "\n"
        prompt += "\nThe complete contract/checklist/image map are embedded below. Do not spend tool calls re-reading them.\n"
        for name in ("instruction.md", "judge_spec.json"):
            contract_text = (packet / name).read_text(encoding="utf-8")
            if name.endswith('.json') and engine == 'responses' and (responses_options or {}).get('compact_tool_facts'):
                contract_text = json.dumps(json.loads(contract_text), ensure_ascii=False, separators=(',', ':'))
            prompt += (
                f"\nBEGIN {name}\n"
                + contract_text
                + f"\nEND {name}\n"
            )
        prompt += "\nIMAGE ORDER AND AVAILABLE EVIDENCE:\n" + json.dumps(
            {k: packet_manifest[k] for k in ("mode", "images", "evidence")},
            ensure_ascii=False,
        )
        if transport_record and image_transport == 'preview_webp':
            prompt += ('\nAttachments are full-frame WebP previews, at most 768 pixels on the long edge. '
                       'Original native scenes and full-resolution evidence remain archived. '
                       'Use diagnostic close-ups for unresolved small details. Do not infer a defect '
                       'solely from preview blur. Cite the original evidence paths from the image map.\n')
        elif transport_record:
            prompt += '\nAttachments use lossless WebP with identical RGBA pixels and original dimensions. The image order above maps each attachment to its original evidence path; cite those original paths.\n'
        if interactive and measurement_catalogue is not None and responses_options:
            prompt += ('\nNATIVE AUDIT: original authored views are already attached. Use native_geometry '
                'for numeric evidence; inspect_scene/render_view only when a semantic ambiguity needs it. '
                'Batch independent measurements in the same response. Do not repeat discovery or '
                'render merely to reproduce attached views. Cite finite numeric leaves rooted at /result/; '
                'objects, strings and booleans are not numeric evidence. Reserve the final round for JSON.\n')
        elif (interactive and engine == 'responses' and
              (responses_options or {}).get('max_rounds') == 1 and
              (responses_options.get('preload_views') or responses_options.get('preload_render_roles'))):
            prompt += ('\nPREPARED NATIVE EVIDENCE: trusted local tools attach their registered '
                'diagnostic renders before this single request. Inspect those images together '
                'with the original authored views and cite their actual registered paths. '
                'No further tool round is available. Native render coverage and input hashes '
                'are still checked by the harness. Diagnostic lighting/cameras show geometry; '
                'evaluate authored appearance only from authored images. Do not infer exact '
                'geometry from object names or boxes. Preserve the frozen observability policy.\n')
        elif interactive:
            prompt += (
                "\nINTERACTIVE BLENDER MODE: Use judge_blender inspect_scene and render_view tools. "
                "First inspect native scenes to discover objects and cameras, then choose views to resolve the checklist. "
                "You MUST render the candidate at least once AND render the reference at least once when it has "
                "a .blend, and inspect both returned images. This is enforced by the harness; do not skip reference "
                "inspection even if the written contract seems sufficient. Choose azimuth/elevation, close-up focus_objects, "
                "frame, authored camera or neutral lighting as needed, and iterate based on the images you receive. "
                "Returned tool images are visible directly; no shell tools needed. Every successful call returns "
                "registered evidence paths under candidate/judge_generated or reference/judge_generated; cite these "
                "paths in issue JSON. Do not cite reserved slots that were not actually produced. "
                "Never edit geometry, materials or the original .blend. A custom close-up, neutral lighting or changed "
                "camera is diagnostic, not proof of an authored composition/lighting failure. Test original appearance "
                "with authored cameras/lighting or original images. Tool failures (missing dependencies, timeout, version) "
                "are infrastructure limitations, not fatal candidate defects. Inspect another view if useful; apply the frozen protocol observability policy to unresolved checks. Do not declare exact geometric properties from AABBs alone. "
                f"Budget: {packet_manifest['tool_budget']} Blender calls total, {render_timeout}s per call. "
                "Aim for 2-4 purposeful renders, reserve time for final JSON. Do not execute submitted source.\n"
            )
        elif packet_manifest["mode"] == "visual":
            prompt += "\nVISUAL MODE: all necessary images and text are attached. Inspect them directly; do not call shell tools.\n"
        else:
            prompt += (
                "\nASSET MODE: perform at least one read-only structural probe of an available native asset "
                "(e.g. parse GLB JSON chunk with Python struct/json to inspect nodes/meshes/transforms). "
                "Preserve the probe under scratch/. Never execute the submitted solution.py. "
                "Use at most three shell calls. Do not dump binary files as text. After one successful "
                "probe, combine its facts with the supplied images and produce the final JSON; "
                "mark remaining unverified checks unobservable instead of continuing open-ended exploration. "
                "Use the private Python at .venv/Scripts/python.exe on Windows, .venv/bin/python on Linux "
                "or /opt/judge-venv/bin/python inside Docker. If tools are unavailable, report that limitation "
                "and mark checks requiring that probe unobservable; do not claim asset inspection.\n"
            )
        measurements_modified = []
        try:
            if engine == 'responses':
                from .responses_runtime import invoke_responses
                result = invoke_responses(work=work, home=home, attempt=attempt, prompt=prompt,
                    model=model, effort=effort, timeout=timeout, images=attached_images, env=env,
                    **(responses_options or {}))
            else:
                result = invoke(command, cwd=work, env=env, prompt=prompt, timeout=timeout)
        finally:
            if runtime == "docker":
                subprocess.run(
                    ["docker", "rm", "-f", container], capture_output=True, check=False
                )
            archive_sessions(home,attempt,secrets)
            if measurements is not None and (measurements / 'generated').is_dir():
                ledger_path = measurements / 'generated/manifest.json'
                if ledger_path.is_file():
                    for relative, expected in read_json(ledger_path)['sha256'].items():
                        file = work / relative
                        if not file.is_file() or digest(file) != expected:
                            measurements_modified.append(relative)
                shutil.copytree(measurements / 'generated', attempt / 'measurements')
        events = redact(result.pop("stdout"), secrets)
        (attempt / "events.jsonl").write_text(events, encoding="utf-8")
        observed=with_archived_usage(attempt,parse_events(events),expected_model=model)
        if engine == 'responses' and observed['usage_coverage'] == 'complete':
            observed['usage_provenance'] = {'source': 'responses_api_request_counters'}
        result.update(usage=observed['usage'],session_ids=observed['session_ids'],
            usage_coverage=observed['usage_coverage'],usage_provenance=observed.get('usage_provenance'),
            session_archive=str(attempt/'session_archive.json'))
        (attempt / "stderr.log").write_text(
            redact(result.pop("stderr"), secrets), encoding="utf-8"
        )
        changed = [
            p
            for p, sha in packet_manifest["sha256"].items()
            if not (work / p).is_file() or digest(work / p) != sha
        ]
        changed.extend(measurements_modified)
        if transport_record:
            for item in transport_record['images']:
                file=work/item['provided']
                if not file.is_file() or digest(file)!=item['provided_sha256']:changed.append(item['provided'])
            result['image_transport']=transport_record
        if interactive:
            generated = private / "generated"
            (attempt / "renderer").mkdir()
            for name in ("blender_tools.py", "blender_worker.py", "image_codec.py", "worker-version.json"):
                shutil.copyfile(private / name, attempt / "renderer" / name)
            if (generated / "manifest.json").exists():
                ledger = read_json(generated / "manifest.json")
                for p, sha in ledger["sha256"].items():
                    if not (work / p).is_file() or digest(work / p) != sha:
                        changed.append(p)
                shutil.copytree(generated, attempt / "generated")
                # Worker logs may contain asset text; apply the same secret scrubber.
                for file in (attempt / "generated").rglob("*.log"):
                    file.write_text(
                        redact(
                            file.read_text(encoding="utf-8", errors="replace"), secrets
                        ),
                        encoding="utf-8",
                    )
        result.update(
            model=model,
            effort=effort,
            runtime=runtime,
            modified_inputs=changed,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            runtime_sha256=digest(Path(__file__)),
        )
        if (work / "response.json").is_file():
            (attempt / "response.json").write_text(
                redact((work / "response.json").read_text(encoding="utf-8"), secrets),
                encoding="utf-8",
            )
        # Preserve scripts/probes written by the judge, with secrets scrubbed.
        scratch = work / "scratch"
        if scratch.is_dir():
            for file in scratch.rglob("*"):
                if (
                    file.is_file()
                    and not file.is_symlink()
                    and file.suffix in {".py", ".json", ".txt"}
                ):
                    dest = attempt / "scratch" / file.relative_to(scratch)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(
                        redact(
                            file.read_text(encoding="utf-8", errors="replace"), secrets
                        ),
                        encoding="utf-8",
                    )
        write_json(attempt / "execution.json", result)
        return result
