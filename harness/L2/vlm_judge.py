"""Blind Agent Judge adapter for audited L2 evidence; no candidate regeneration."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

from dotenv import dotenv_values
from jsonschema import ValidationError

from src.agent_judge.generated import verified_evidence
from src.agent_judge.packet import prepare
from src.agent_judge.protocol import digest, read_json, score, write_json
from src.agent_judge.runtime import run_codex
from src.agent_judge import l2_fidelity, image_continuous, task_continuous, strict_continuous


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    effort: str = 'medium'
    timeout: float = 300.
    attempts: int = 6
    codex: str = 'codex'
    codex_home: Path = Path.home()/'.codex'
    api_key: str = field(default='',repr=False)
    base_url: str = ''
    engine: str = 'codex'
    responses_options: dict = field(default_factory=dict, repr=False)
    inspection_guidance: str | None = field(default=None, repr=False)
    image_transport: str = 'original'

    def __post_init__(self):
        if (not self.model or type(self.attempts) is not int or not 1 <= self.attempts <= 6
                or not math.isfinite(self.timeout) or self.timeout <= 0
                or self.effort not in {'low','medium','high','xhigh','max'}):
            raise ValueError('Invalid VLM model, effort, timeout or attempts (maximum 6 = 5 retries)')

    @classmethod
    def from_env(cls, env_file=None):
        file_settings={k:v for k,v in dotenv_values(env_file or Path(__file__).parents[2]/'.env').items() if v is not None}
        settings = {**os.environ, **file_settings}
        credentials=file_settings if any(file_settings.get(k) for k in ('VLM_API_KEY','OPENAI_DATA_API_KEY','OPENAI_API_KEY')) else settings
        # Explicit VLM configuration wins; never pass the tested model as a prompt.
        return cls(model=settings.get('VLM_MODEL') or settings.get('OPENAI_MODEL') or 'gpt-5.6-luna',
            effort=settings.get('VLM_REASONING_EFFORT','medium'),
            timeout=float(settings.get('VLM_TIMEOUT','300')),attempts=int(settings.get('VLM_MAX_ATTEMPTS','6')),
            codex=settings.get('VLM_CODEX_BIN') or settings.get('GENERATOR_CODEX_BIN') or 'codex',
            codex_home=Path(settings.get('CODEX_HOME',Path.home()/'.codex')),
            api_key=(credentials.get('VLM_API_KEY') or credentials.get('OPENAI_DATA_API_KEY')
                     or credentials.get('OPENAI_API_KEY','')),
            base_url=settings.get('VLM_BASE_URL') or settings.get('OPENAI_BASE_URL',''))


def bound_copy(item, destination):
    source = Path(item['path']).resolve(strict=True)
    if not item.get('sha256') or digest(source) != item['sha256']:
        raise ValueError('Judge image/native evidence changed')
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
    if digest(destination) != item['sha256']:
        raise ValueError('Judge copy digest mismatch')


def bound_native_assets(evidence, candidate, bindings):
    """Copy explicitly audited portable assets, keeping their relative paths."""
    native = evidence.get('artifacts', {}).get('scene.blend')
    if not native:
        raise ValueError('Native assets require a bound scene')
    root = Path(native['path']).resolve().parent
    for name, item in evidence.get('native_assets', {}).items():
        relative = Path(name)
        if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) < 2
                or relative.parts[0] != 'assets' or relative.as_posix() != name):
            raise ValueError('Native asset must use an output/assets relative path')
        source = Path(item['path'])
        if source.is_symlink() or source.resolve() != root/relative:
            raise ValueError('Native asset is outside the selected scene output')
        bound_copy(item, candidate/relative)
        bindings[str(source.resolve())] = item['sha256']


def verify_packet(packet, manifest):
    for name, expected in manifest['sha256'].items():
        file = (packet/name).resolve(strict=True)
        if not file.is_relative_to(packet.resolve()) or digest(file) != expected:
            raise ValueError('Judge packet changed')


def judge_task(task_root, evidence, plan, output, *, config=None, env_file=None,
               tested_model=None, blender=None, deadline=None, invoke=run_codex):
    """First valid answer wins, including a low score or needs_review result.

    Retries only repair process/JSON/evidence failures. Each attempt is isolated;
    no judge score or private reference is sent back to the generation harness.
    """
    task_root, output = Path(task_root).resolve(), Path(output).resolve()
    blender = Path(blender).expanduser().resolve() if blender else None
    output.mkdir(parents=True,exist_ok=True)
    if os.environ.get('THREEDBENCH_DEFER_JUDGES')=='1':
        return {'status':'not_measurable','S_vlm':None,'deferred':True,
                'reason':'Judge deferred until all campaign generations finish'}
    metadata = {'attempts':[]}
    try:
        config = config or JudgeConfig.from_env(env_file)
        metadata.update(model=config.model,reasoning_effort=config.effort,
            self_judge=bool(tested_model and tested_model == config.model),tested_model=tested_model,
            max_attempts=config.attempts,max_retries=config.attempts-1,selection='first_valid_judgment_no_score_selection',
            invocation={'engine':config.engine,'image_transport':config.image_transport,
                        'responses_options':config.responses_options,
                        'inspection_guidance':config.inspection_guidance})
        frozen = plan['_vlm_judge']; spec = frozen['spec']; mode = frozen['mode']
        strict_protocol = ({l2_fidelity.PROTOCOL: l2_fidelity,
                            strict_continuous.PROTOCOL: strict_continuous,
                            image_continuous.PROTOCOL: image_continuous,
                            task_continuous.PROTOCOL: task_continuous}.get(spec['protocol']))
        fidelity = strict_protocol is not None
        candidate_names = ['main.png', 'alternate.png'] + (['novel.png'] if 'novel.png' in evidence.get('artifacts', {}) else [])
        if strict_protocol in {task_continuous, strict_continuous}:
            candidate_names += [Path(p).name for c in spec['checks'] for p in c['required_evidence'] if p.startswith('candidate/')]
        elif strict_protocol is image_continuous:
            candidate_names += [Path(p['candidate']).name for p in spec['view_pairs']]
        candidate_names = list(dict.fromkeys(candidate_names))
        if (output/'run.json').exists():
            previous=read_json(output/'run.json')
            if previous.get('invocation', metadata['invocation']) != metadata['invocation']:
                raise ValueError('Cannot resume a judge with changed invocation settings')
            if (previous.get('model')!=config.model or previous.get('reasoning_effort')!=config.effort
                    or previous.get('tested_model')!=tested_model or previous.get('spec_sha256')!=frozen['spec_sha256']
                    or previous.get('max_attempts')!=config.attempts or previous.get('mode')!=mode):
                raise ValueError('Cannot resume a judge with changed model/spec/attempt budget')
            packet=output/'packet';manifest=read_json(packet/'manifest.json')
            if digest(packet/'manifest.json')!=previous['packet_sha256']:raise ValueError('Resume packet changed')
            verify_packet(packet,manifest);bindings=previous['source_bindings']
            for path,expected in bindings.items():
                if digest(Path(path))!=expected:raise ValueError('Resume source evidence changed')
            for name in candidate_names:
                if manifest['sha256'].get('candidate/'+name)!=evidence['artifacts'][name]['sha256']:raise ValueError('Resume candidate changed')
            if fidelity:
                strict_protocol.verify_packet_inputs(spec,manifest)
                wanted={f'reference/reference-{i}{Path(item["path"]).suffix.lower()}':item['sha256']
                    for i,(_,item) in enumerate(sorted(evidence.get('reference_images',{}).items()))} if spec['family']!='Brief2Scene' else {}
                if wanted != {k:v for k,v in manifest['sha256'].items() if k.startswith('reference/reference-')}:
                    raise ValueError('Resume public reference population changed')
                if mode=='interactive' and manifest['sha256'].get('candidate/scene.blend')!=evidence['artifacts']['scene.blend']['sha256']:
                    raise ValueError('Resume native candidate changed')
                if spec['family']=='SceneEdit':
                    for role,item in frozen['edit_context'].items():
                        if manifest['sha256'].get('reference/'+role+'.png')!=item['sha256']:
                            raise ValueError('Resume edit context changed')
            metadata.update(attempts=previous['attempts'],packet_sha256=previous['packet_sha256'],
                spec_sha256=previous['spec_sha256'],source_bindings=bindings,mode=mode)
            if previous.get('accepted_attempt'):
                if digest(output/'issues.json')!=previous['response_sha256']:raise ValueError('Accepted response changed')
                directory=output/f"attempt-{previous['accepted_attempt']}"
                paths=verified_evidence(manifest,directory/'generated' if mode=='interactive' else None)
                recovered=score(read_json(output/'issues.json'),spec,paths)
                if recovered.get('localization'):recovered['localization']['image_sha256']=evidence['artifacts']['main.png']['sha256']
                if recovered['S_vlm']!=previous['S_vlm']:raise ValueError('Accepted score replay mismatch')
                return {**previous,**recovered}
            for row in metadata['attempts']:
                if 'status' not in row:row.update(status='failed',reason='process_interrupted; counted against the six-attempt total')
        else:
            staging = output/'staging'; candidate=staging/'candidate'; reference=staging/'reference'
            candidate.mkdir(parents=True);reference.mkdir()
            bindings = {}
            for name in candidate_names:
                item = evidence.get('artifacts',{}).get(name)
                if not item:raise ValueError('Audited main and alternate renders required for VLM')
                bound_copy(item,candidate/name);bindings[str(Path(item['path']).resolve())]=item['sha256']
            if spec['family'] != 'Brief2Scene':
                references=evidence.get('reference_images',{})
                if not references and not (strict_protocol in {task_continuous, strict_continuous} and spec['family'] == 'SceneEdit'):
                    raise ValueError('Reference/edit judge requires bound reference images')
                for index,(name,item) in enumerate(sorted(references.items())):
                    dest=reference/f'reference-{index}{Path(item["path"]).suffix.lower()}'
                    bound_copy(item,dest);bindings[str(Path(item['path']).resolve())]=item['sha256']
            if frozen.get('version') in {'l2-vlm-judge-v2','l2-vlm-judge-v3','continuous-task-judge-v1'} and spec['family'] == 'SceneEdit':
                for role in ['before','target']:
                    item=frozen['edit_context'][role]
                    source=task_root/item['path']
                    bound_copy({'path':str(source),'sha256':item['sha256']},reference/(role+'.png'))
                    bindings[str(source)]=item['sha256']
            if mode == 'interactive':
                if not blender:raise ValueError('Interactive VLM requires Blender')
                native=evidence.get('artifacts',{}).get('scene.blend')
                if not native:raise ValueError('Audited native candidate required')
                bound_copy(native,candidate/'scene.blend');bindings[str(Path(native['path']).resolve())]=native['sha256']
                bound_native_assets(evidence, candidate, bindings)
                # Assets in the current L2 protocol must be packed in the audited blend.
                # Only a frozen reference scene may be exposed, never the private rubric.
                scene=plan.get('reference_target',{}).get('scene')
                if scene and not fidelity:
                    file=task_root/scene;item={'path':str(file),'sha256':digest(file)}
                    bound_copy(item,reference/'scene.blend');bindings[str(file)]=item['sha256']
            packet=output/'packet'
            manifest=prepare(task_root,candidate,spec,packet,mode=mode,reference=reference,tool_budget=12)
            if fidelity:strict_protocol.verify_packet_inputs(spec,manifest)
            metadata.update(packet_sha256=digest(packet/'manifest.json'),spec_sha256=frozen['spec_sha256'],
                source_bindings=bindings,mode=mode)
            shutil.rmtree(staging)  # All accepted evidence is now in the immutable packet.
        # Credentials stay outside the archived packet/run and are removed on exit.
        with tempfile.TemporaryDirectory(prefix='l2-vlm-auth-') as auth_temp:
            auth_source=config.codex_home
            if config.api_key:
                auth_source=Path(auth_temp)
                write_json(auth_source/'auth.json',{'OPENAI_API_KEY':config.api_key})
                os.chmod(auth_source/'auth.json',0o600)
                if config.base_url:
                    (auth_source/'config.toml').write_text('model_provider = "l2_judge"\n[model_providers.l2_judge]\nname = "L2 Judge"\nwire_api = "responses"\nrequires_openai_auth = true\nbase_url = '+json.dumps(config.base_url)+'\n')
            for attempt in range(len(metadata['attempts'])+1,config.attempts+1):
                remaining=config.timeout if deadline is None else min(config.timeout,deadline-time.monotonic())
                if remaining <= 0:break
                directory=output/f'attempt-{attempt}'
                row={'attempt':attempt,'timeout_seconds':remaining};metadata['attempts'].append(row)
                write_json(output/'run.json',{**metadata,'status':'running'})
                try:
                    verify_packet(packet,manifest)
                    execution=invoke(packet,directory,model=config.model,effort=config.effort,codex=config.codex,
                        codex_home=auth_source,timeout=remaining,blender=str(blender) if blender else None,
                        api_key=config.api_key or None,
                        retry_feedback=metadata['attempts'][-2].get('reason') if len(metadata['attempts'])>1 else None,
                        engine=config.engine, image_transport=config.image_transport,
                        responses_options=config.responses_options,
                        inspection_guidance=config.inspection_guidance)
                    if execution.get('timed_out') or execution.get('returncode') != 0 or execution.get('modified_inputs'):
                        row.update(status='failed',reason='timeout' if execution.get('timed_out') else
                            'modified_evidence' if execution.get('modified_inputs') else 'judge_process_error',execution=execution)
                        continue
                    verify_packet(packet,manifest)
                    response=read_json(directory/'response.json')
                    paths=verified_evidence(manifest,directory/'generated' if mode=='interactive' else None)
                    judgment=score(response,spec,paths)
                    for path,expected in bindings.items():
                        if digest(Path(path))!=expected:raise ValueError('Original VLM evidence changed')
                    if judgment.get('localization'):
                        judgment['localization']['image_sha256']=evidence['artifacts']['main.png']['sha256']
                    row.update(status='accepted',execution=execution)
                    write_json(output/'issues.json',response);write_json(output/'score.json',judgment)
                    result={**judgment,**metadata,'summary':response['summary'],'checks':response['checks'],
                        'issues':response.get('issues',[]),'accepted_attempt':attempt,
                        'response_sha256':digest(output/'issues.json'),'score_sha256':digest(output/'score.json'),
                        'run_path':str(output/'run.json')}
                    write_json(output/'run.json',result)
                    return result
                except (OSError, ValueError, RuntimeError, ValidationError) as error:
                    reason=str(error).replace(config.api_key,'<redacted>') if config.api_key else str(error)
                    row.update(status='failed',reason=type(error).__name__+': '+reason[:400])
        result={**metadata,'status':'not_measurable','S_vlm':None,
            'reason':'VLM attempts/budget exhausted; no model quality score established'}
    except (OSError, ValueError, RuntimeError, ValidationError) as error:
        reason=str(error).replace(config.api_key,'<redacted>') if config and config.api_key else str(error)
        result={**metadata,'status':'not_measurable','S_vlm':None,'reason':type(error).__name__+': '+reason[:400]}
    write_json(output/'run.json',result)
    return result
