"""Level-neutral Codex trial orchestration used by L2/L3 wrappers."""
from __future__ import annotations
import json, os, shutil, tempfile, time
from dataclasses import replace
from src.generator.harnesses import model_effort, model_contract
from pathlib import Path
from typing import Any
from src.generator.client import GeneratorConfig, build_generation_command as build_codex_command
from src.generator.task_adapter import load_benchmark_task
from .attempt_log import sha256, sha256_bytes, write_json
from .codex_invoker import Invocation, run_once
from .config import HarnessConfig

def _retryable(inv: Invocation, cfg: HarnessConfig) -> bool:
    return {"timeout": cfg.retry_timeout, "process_error": cfg.retry_transport_error, "empty_output": cfg.retry_empty_output, "protocol_error": cfg.retry_protocol_error}.get(inv.status, False)

def run_trial(*, task_id: str, tasks_root: Path, config_path: Path, output_dir: Path, level: int, task_prefix: str, env_file: Path | None = None, trial_id: str = "0") -> dict[str, Any]:
    from .config import load_config
    task = load_benchmark_task(task_id, tasks_root)
    if task.level != level: raise ValueError(f"{task_id} is not a level {level} task")
    cfg = load_config(config_path, level=level, task_prefix=task_prefix)
    if cfg.task_id != task.task_id: raise ValueError("Harness task_id does not match task")
    task.validate_materialized_assets()
    output_dir = output_dir.expanduser().resolve(); output_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{task_id.replace('/', '__')}__trial-{trial_id}__{int(time.time())}"
    run_dir = output_dir / "harness" / run_id; run_dir.mkdir(parents=True)
    prompt = f"You are completing benchmark task {task.task_id}.\n\n{task.instruction.strip()}\n\nAllowed environment files:\n" + ("\n".join(f"- {p}" for p in task.environment_files) or "- (none)") + "\nCreate the requested deliverables in the workspace."
    manifest = {"schema_version": 1, "run_id": run_id, "task_id": task.task_id, "trial_id": trial_id, "harness_version": cfg.harness_version, "harness_config_sha256": cfg.digest, "model": os.environ.get(cfg.model_env), "level": level, "timeout_seconds": cfg.timeout_seconds, "max_total_seconds": cfg.max_total_seconds, "max_retries": cfg.max_retries, "prompt_sha256": sha256_bytes(prompt.encode()), "started_at": time.time()}
    write_json(run_dir / "run_manifest.json", manifest)
    attempts: list[dict[str, Any]] = []; started = time.monotonic(); final: Invocation | None = None; final_workspace: Path | None = None
    base_generator_cfg = GeneratorConfig.from_env(env_file)
    generator_cfg = replace(base_generator_cfg, max_attempts=1, reasoning_effort=model_effort(base_generator_cfg.model) if model_contract(base_generator_cfg.model) else cfg.reasoning_effort or base_generator_cfg.reasoning_effort)
    max_calls = cfg.max_retries + 1
    with tempfile.TemporaryDirectory(prefix=f"l{level}-input-") as temp_name:
        stage = Path(temp_name); task.stage_environment(stage)
        input_hashes = {p.as_posix(): sha256(stage / p) for p in task.environment_files}
        for index in range(1, max_calls + 1):
            remaining = cfg.max_total_seconds - (time.monotonic() - started)
            if remaining <= 0: break
            attempt_dir = run_dir / f"attempt-{index:04d}"; attempt_dir.mkdir()
            workspace = attempt_dir / "workspace"; shutil.copytree(stage, workspace)
            output_path = workspace / ".codex_last_message.txt"
            command = build_codex_command(generator_cfg, output_path=output_path, working_directory=workspace, image_paths=[workspace / p for p in task.image_files], sandbox_mode="workspace-write")
            invocation = run_once(command, prompt, cwd=workspace, output_path=output_path, timeout=min(cfg.timeout_seconds, remaining), env={**os.environ, "CODEX_API_KEY": generator_cfg.api_key})
            (attempt_dir / "stdout.log").write_text(invocation.stdout, encoding="utf-8")
            (attempt_dir / "stderr.log").write_text(invocation.stderr, encoding="utf-8")
            result = {"attempt": index, "status": invocation.status, "error_code": invocation.error_code, "return_code": invocation.return_code, "elapsed_seconds": invocation.elapsed_seconds, "stdout_sha256": sha256_bytes(invocation.stdout.encode()), "stderr_sha256": sha256_bytes(invocation.stderr.encode()), "output_sha256": sha256(output_path) if output_path.is_file() else None}
            write_json(attempt_dir / "result.json", result); attempts.append(result); final, final_workspace = invocation, workspace
            if invocation.status == "success":
                for relative in cfg.output_files:
                    source = workspace / relative
                    if source.is_symlink() or not source.resolve().is_relative_to(workspace.resolve()):
                        raise ValueError(f"Unsafe generated artifact: {relative}")
                    if source.is_file() and source.stat().st_size:
                        destination = run_dir / "outputs" / relative; destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
                    elif source.is_dir():
                        destination = run_dir / "outputs" / relative; shutil.copytree(source, destination, dirs_exist_ok=True)
                break
            if index >= max_calls or not _retryable(invocation, cfg): break
            delay = cfg.backoff_seconds[min(index - 1, len(cfg.backoff_seconds)-1)]
            if delay >= max(0, cfg.max_total_seconds - (time.monotonic() - started)): break
            time.sleep(delay)
        output_hashes = {}
        for relative in cfg.output_files:
            path = run_dir / "outputs" / relative
            if path.is_file(): output_hashes[relative] = sha256(path)
        final_status = final.status if final else "budget_exhausted"
        record = {"schema_version": 1, "harness_version": cfg.harness_version, "task_id": task.task_id, "trial_id": trial_id, "run_id": run_id, "evaluator_version": None, "spec_sha256": None, "artifact_sha256": output_hashes, "generation_passed": final_status == "success", "execution_passed": False, "integrity_passed": False, "seed_runs": {}, "attempt_count": len(attempts), "final_status": final_status, "attempts": attempts, "input_sha256": input_hashes, "total_seconds": time.monotonic() - started, "model_calls": len(attempts)}
        write_json(run_dir / "artifacts.json", {"input_sha256": input_hashes, "outputs": output_hashes})
        write_json(run_dir / "harness_record.json", record)
    manifest.update({"finished_at": time.time(), "attempt_count": len(attempts), "final_status": final_status})
    write_json(run_dir / "run_manifest.json", manifest)
    return {"run_dir": str(run_dir), "harness_record": str(run_dir / "harness_record.json"), "final_status": final_status, "attempt_count": len(attempts)}
