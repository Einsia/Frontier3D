"""New task-contract generation; no generator/retry code in task harnesses."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

from harness.L1.common.bundle import BUNDLE_SCHEMA, MAX_RESPONSE_BYTES, decode_response
from src.generator.client import GeneratorConfig, GeneratorError, build_generation_command
from src.run_usage import parse_events

from .feedback import exception_detail, redact, repair_prompt, retry_policy
from .runtime import retry, run_process
from .tasks import regular, relative, sha256, write_json

PROMPT = '''Return one JSON l1-submission-bundle-v1 object with protocol, entrypoint,
files, runtime, dependencies, run_instructions. Each file has path, encoding
(utf-8 or base64), content. Paths are relative to output/. Entrypoint is solution.py.
Include solution.py, README.md and required helper/assets files. Do not return
generated scene.blend/scene.glb/main.png. Follow the instruction below exactly:
your script receives --input-dir and --output-dir after Blender's -- separator,
and MUST save scene.blend and export scene.glb itself into output-dir. The runner
does not save them for you. Required main.png must also be rendered by your script.
Read only the staged public input/ files. Do not search elsewhere or retrieve assets.
The workspace is read-only. Return files in the JSON response; do not write files.
Generation and execution are separate stages. This generation container is for
inspecting the supplied public inputs and authoring the complete JSON bundle;
it may not have Python or Blender installed. After you submit the bundle, the
existing validator executes the entrypoint in its configured Blender runtime
and returns public execution errors if another attempt is needed. Continue to
read and analyze necessary public inputs with available tools, including blend
files. Installing or repairing a runtime in this generation container is not a
prerequisite for submission: do not spend turns trying to fix missing runtime
tools. Declare the dependencies required by your submitted code in the bundle.
'''


def l2_runtime_policy_prompt(task):
    """Public runtime facts, independent of the task's private grading material."""
    if task.manifest['level'] != 2:
        return ''
    return '''
L2 runtime contract (Blender 5.2.1, Linux headless):
- Bundle file paths are relative to the output directory: use "solution.py" and
  "README.md", never "output/solution.py" or "output/README.md". Do not nest them.
- Parse only arguments after Blender's separator, for example:
  argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
  args = parser.parse_args(argv)
  Read --input-dir and write all required artifacts inside --output-dir.
- Use the installed API: Eevee's engine identifier is 'BLENDER_EEVEE', never
  'BLENDER_EEVEE_NEXT'; CYCLES with CPU rendering is also available. Preserve
  the task's required render engine/settings when editing an input scene.
- Obtain the evaluated depsgraph with bpy.context.evaluated_depsgraph_get(),
  not scene.evaluated_depsgraph_get(). Legacy scene.eevee settings are unavailable.
- A factory-empty scene may have scene.world=None; create and assign a World
  before configuring it. Clear/reset the scene before creating new materials
  and objects; do not reuse datablock references that have been removed.
- Keep both final cameras in scene.blend and explicitly save the scene and both
  PNG images. There is no graphical UI and the runner does not save them for you.
These are execution instructions, not additional content scoring requirements.
'''


def l1_codeedit_runtime_policy_prompt(task):
    """Public installed-runtime facts, without private references or answers."""
    if task.manifest['level'] != 1 or task.manifest.get('category') != 'CodeEdit':
        return ''
    return '''
L1 CodeEdit runtime contract (Blender 5.2.1, Linux headless):
- Bundle paths are relative to output: use solution.py and README.md, not
  output/solution.py. Parse script arguments only after Blender's -- separator.
- Open the supplied initial.blend before making the requested local edit.
  Preserve non-target geometry, world, lights, cameras and used materials.
- The installed Eevee engine identifier is BLENDER_EEVEE. BLENDER_EEVEE_NEXT
  is not supported and raises TypeError. Do not select it based on
  hasattr(scene, 'eevee'); that condition does not establish engine support.
  CYCLES CPU is also available. Keep existing render settings unless the task
  explicitly requires a change; local geometry edits do not require new lights.
- The evaluator starts from a factory-empty scene and does not save outputs
  for you. Save scene.blend and export scene.glb to --output-dir explicitly.
  Only create PNG files when the task requires them; optional beauty rendering
  is not required for CodeEdit scoring and must not prevent GLB delivery.
- Use bpy.context.evaluated_depsgraph_get(), not scene.evaluated_depsgraph_get().
  A new empty scene may have world=None. Do not use legacy scene.eevee settings.
These are execution facts, not private scoring targets or extra content requirements.
'''


def l1_image_runtime_policy_prompt(task):
    if task.manifest['level'] != 1 or not task.manifest.get('category', '').startswith('Image2Code'):
        return ''
    return '''
L1 image reconstruction runtime (Blender 5.2.1, Linux headless):
- Parse only arguments after Blender's -- separator; paths in the returned
  bundle are relative to output, not prefixed with output/.
- Use bpy.context.evaluated_depsgraph_get(). The installed Eevee identifier is
  BLENDER_EEVEE, never BLENDER_EEVEE_NEXT. CYCLES CPU is available; obey the
  engine and image dimensions specified in the public task.
- An empty scene may have world=None; create and assign a World if necessary.
- Save the final assembled camera, materials, lights and render settings in
  scene.blend. Render required main.png from that same scene/camera at the frame
  specified by the task (normally 1; the refreshed cabinet motion task uses 61).
  Save scene.blend and export scene.glb explicitly to --output-dir, retaining
  animation only where the public task requires it.
- Keep renders reproducible: use a fixed render seed and consistent settings.
- Blender 5.2 uses layered/slotted Actions: Action.fcurves is unavailable.
  For simple animation use object.keyframe_insert and retain default interpolation.
  If you must access curves, use the action layer/strip channelbag for the object's
  action_slot, then channelbag.fcurves; do not iterate action.fcurves.
- Export GLB with bpy.ops.export_scene.gltf(export_format='GLB', filepath=...).
  bpy.ops.wm.gltf_export does not exist. Object.parent must be an Object, not a Collection.
These are runtime facts, not extra content requirements or private targets.
'''


def generate(task, root, *, deadline, timeout, attempts, env_file=None, runtime='docker', image=None,
             validate_submission=None, config=None, usage_sink=None, resume=False):
    policy = retry_policy(attempts)
    if validate_submission is None:
        policy['selection'] = 'first_valid_bundle'
    config = config or GeneratorConfig.from_env(env_file)
    from src.generator.harnesses import model_effort
    config = replace(config, runtime=runtime, max_attempts=1, timeout=timeout, reasoning_effort=model_effort(config.model),
                     docker_image=image or config.docker_image)
    input_root = root / 'model-input'
    if not resume:
        task.stage(input_root)
    input_hashes = {str(p.relative_to(input_root)): sha256(p) for p in input_root.rglob('*') if p.is_file()}
    images = tuple(input_root / p for p in task.manifest['environment_files'] if Path(p).suffix.lower() in {'.png', '.jpg', '.jpeg'})
    prompt = PROMPT
    if task.manifest['level'] == 2:
        prompt = prompt.replace('and export scene.glb', 'and render main.png and alternate.png')
        prompt += '\nKeep both final cameras in scene.blend. No GLB export is required for this task.\n'
    runtime_rule = l2_runtime_policy_prompt(task) or l1_codeedit_runtime_policy_prompt(task) or l1_image_runtime_policy_prompt(task)
    prompt += runtime_rule+'\n'+regular(task.root, task.manifest['instruction']).read_text()
    context = {
        'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
        'prompt': prompt,
        'public_runtime_rule': runtime_rule, 'retry_policy': policy,
    }
    if config.harness != 'codex':
        context['generator_harness'] = config.harness
    history = []
    if resume:
        prior = json.loads((root / 'generation.json').read_text())
        previous_context = json.loads((root / 'generation_context.json').read_text())
        if prior['input_sha256'] != input_hashes or previous_context != context:
            raise ValueError('Cannot resume after public inputs or generation policy changed')
        history = prior['attempts']
        if any(r['attempt'] != i+1 or r['model'] != config.model for i,r in enumerate(history)):
            raise ValueError('Invalid generation resume history')
        if history and history[-1]['status'] == 'success':
            # Acceptance may precede a process stop before the campaign freezes
            # its source. Recover the delivery without another model invocation.
            accepted = history[-1]
            response = regular(root / f"generation-{accepted['attempt']-1:02d}" / 'response', 'bundle.json')
            if sha256(response) != accepted['response_sha256']:
                raise ValueError('Accepted generation response changed')
            _, bundle = decode_response(response.read_text(), allow_prefixed_bundle=config.model == 'qwen3.8-max')
            source = Path(accepted['submission'])
            from .runner import tree_files
            if bundle is None or set(tree_files(source)) != set(bundle['files']):
                raise ValueError('Accepted generated source changed')
            if any(regular(source, name).read_bytes() != data for name, data in bundle['files'].items()):
                raise ValueError('Accepted generated source changed')
            if validate_submission is not None:
                validations = accepted.get('validation_attempts', [])
                if not validations or validations[-1]['status'] != 'success':
                    raise ValueError('Accepted public execution is missing')
            return source, history
        if not history or len(history) >= attempts:
            raise ValueError('No remaining failed generation attempts to resume')
    else:
        write_json(root / 'generation_context.json', context)
    offset = len(history)

    def save_history():
        write_json(root / 'generation.json', {'attempts': history, 'input_sha256': input_hashes,
            'total_tokens': sum(r['tokens'] for r in history) if history and all(r.get('tokens') is not None for r in history) else None,
            'model_call': True, 'retry_policy': policy,
            'execution_validation': validate_submission is not None})

    def attempt(index, end):
        directory = root / f'generation-{index:02d}'
        directory.mkdir()
        attempt_prompt = prompt
        if history:
            attempt_prompt, feedback = repair_prompt(prompt, history[-1],
                root / f'generation-{index-1:02d}', secrets=(config.api_key,))
            write_json(directory / 'feedback.json', feedback)
        (directory / 'prompt.txt').write_text(attempt_prompt)
        delivery = directory / 'response'
        delivery.mkdir()
        response = delivery / 'bundle.json'
        schema = directory / 'bundle-schema.json'
        write_json(schema, BUNDLE_SCHEMA)
        session_root=directory/('claude-home' if config.harness=='claude-code' else 'codex-home');session_root.mkdir(mode=0o700)
        command = build_generation_command(config, response, input_root, image_paths=images, output_schema=schema,
                                      session_root=session_root,json_events=True)
        container = None
        if config.runtime == 'docker':
            container = '3dbench-generator-'+uuid.uuid4().hex
            limits = ['--name', container, '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                      '--pids-limit', '128', '--memory', '4g', '--cpus', '2']
            # Docker's default bridge is a single /24 (254 usable IPs) shared with
            # every container on the host, so running several models concurrently
            # exhausts it and each new container dies with "no available IPv4
            # addresses" -- indistinguishable from a model failure in the logs.
            # Every harness routes through here, so this is the one place the
            # network has to be set. Unset -> unchanged default-bridge behaviour.
            network = os.environ.get('THREEDBENCH_GENERATOR_NETWORK', '').strip()
            if network:
                limits += ['--network', network]
            command[2:2] = limits
        row = {'status': 'running', 'model': config.model, 'runtime': config.runtime, 'tokens': None, 'attempt': index+1,
               'prompt_sha256': sha256(directory / 'prompt.txt'), 'failure_phase': 'generation'}
        if config.harness != 'codex':row['harness'] = config.harness
        adapter_receipt = session_root/'harness-adapter.json'
        if adapter_receipt.exists():
            row['harness_adapter'] = json.loads(adapter_receipt.read_text())
            row['harness_adapter']['receipt_path'] = str(adapter_receipt)
            row['harness_adapter']['snapshot_path'] = str(session_root/'harness-adapter.py')
        if index:
            row.update(feedback_sha256=sha256(directory / 'feedback.json'), retry_of=index)
        history.append(row)
        save_history()
        def record_usage():
            def log(name):
                file = directory / 'process' / name
                return file.read_text(errors='replace') if file.is_file() else ''
            observed = parse_events(log('stdout.log'), log('stderr.log'))
            row.update(usage=observed['usage'], session_ids=observed['session_ids'],
                       session_root=str(session_root), tokens=(observed['usage'] or {}).get('total_tokens'))
            write_json(directory / 'session.json', {**observed,
                'events_path': str(directory / 'process/stdout.log'),
                'session_root': str(session_root), 'isolated_attempt': True})
            if usage_sink is not None:
                usage_sink(directory, dict(row))
        try:
            process_options = ({'max_pipe_bytes': 64*1024*1024}
                               if config.model == 'qwen3.8-max' else {})
            execution = run_process(command, cwd=input_root, directory=directory / 'process',
                                    deadline=end, timeout=timeout, container=container,
                                    docker_binary=config.docker_binary, input_bytes=attempt_prompt.encode(),
                                    env={'CODEX_API_KEY': config.api_key, 'CODEX_HOME':str(session_root.resolve())},
                                    **process_options)
        except BaseException as error:
            row.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'infrastructure_error',
                       error=redact(exception_detail(error), (config.api_key,)), retryable=False)
            if hasattr(error, 'orchestrator_execution'):
                row['execution'] = error.orchestrator_execution
            record_usage()
            write_json(directory / 'generation.json', row)
            save_history()
            raise
        row.update(status=execution['status'], execution=execution)
        record_usage()
        if row['status'] == 'success':
            try:
                path = regular(delivery, 'bundle.json')
                if path.stat().st_size > MAX_RESPONSE_BYTES:
                    raise ValueError('Model response exceeds bundle limit')
                row['response_sha256'] = sha256(path)
                _, bundle = decode_response(path.read_text(),
                                            allow_prefixed_bundle=config.model == 'qwen3.8-max')
                if bundle is None or bundle['manifest']['entrypoint'] != 'solution.py':
                    raise ValueError('Task instances require a solution.py bundle')
                target = directory / 'submission'
                target.mkdir()
                for name, data in bundle['files'].items():
                    if name in {'scene.blend', 'scene.glb', 'main.png', 'alternate.png', 'novel.png'}:
                        raise ValueError('Generated artifacts are not source files')
                    path = target / relative(name)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                regular(target, 'README.md')
                row['submission'] = str(target)
            except (ValueError, OSError, TypeError, GeneratorError) as error:
                row.update(status='invalid_submission', error_type=type(error).__name__,
                           error=redact(exception_detail(error), (config.api_key,)), failure_phase='delivery')
        try:
            row['inputs_unchanged'] = all(sha256(regular(input_root, name)) == digest for name, digest in input_hashes.items())
        except (ValueError, OSError):
            row['inputs_unchanged'] = False
        if not row['inputs_unchanged']:
            row.update(status='input_changed', retryable=False, error='Public model inputs changed during generation')
        if row['status'] == 'success' and validate_submission is not None:
            row.update(status='validating', failure_phase='execution')
            save_history()
            try:
                validations = validate_submission(Path(row['submission']), directory, end)
            except BaseException as error:
                row.update(status='interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else 'validation_error',
                           error=redact(exception_detail(error), (config.api_key,)), retryable=False)
                write_json(directory / 'generation.json', row)
                save_history()
                raise
            row['validation_attempts'] = validations
            if validations and validations[-1]['status'] == 'success':
                row['status'] = 'success'
            else:
                row.update(status='execution_failed', failure_phase='execution',
                           error='Candidate failed public execution/delivery validation; see validation_attempts')
                if validations and validations[-1]['status'] in {'cleanup_failed', 'interrupted'}:
                    row['retryable'] = False
        if row['status'] == 'success':
            row['failure_phase'] = None
        if execution['status'] in {'cleanup_failed', 'interrupted'}:
            row['retryable'] = False
        write_json(directory / 'generation.json', row)
        save_history()
        return row

    retry(lambda index,end: attempt(index+offset,end), attempts=attempts-offset, deadline=deadline, backoff=1)
    if not history or history[-1]['status'] != 'success':
        phase = history[-1]['failure_phase'] if history else 'budget_exhausted'
        raise RuntimeError(f'Generation failed after {len(history)} model calls ({phase}); see generation.json')
    return Path(history[-1]['submission']), history
