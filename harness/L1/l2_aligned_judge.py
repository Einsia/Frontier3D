"""Reuse the L2 judge runtime with a frozen L1 rubric and audited color renders.

This trusted orchestrator API does not render or execute candidate code, infer
missing views, or launch implicitly from legacy L1 evaluation.
"""
from pathlib import Path

from harness.L2.vlm_judge import judge_task, verify_packet
from orchestrator.tasks import sha256
from src.agent_judge.protocol import contract_hash, read_json, score, write_json
from src.agent_judge.generated import verified_evidence
from src.evaluator.l1_l2_alignment import BRIEF, digest, validate_plan
from src.agent_judge.runtime import run_codex


def require_reference_coverage(response, references):
    """Evidence completeness, never a retry based on low quality grades."""
    if response.get('evidence_status') == 'infrastructure_error':
        return
    cross = next((r for r in response.get('checks', []) if r.get('check_id') == 'cross_view'), None)
    if cross is None:
        raise ValueError('Missing required cross_view criterion')
    cited = {e['file'] for e in cross.get('evidence', [])}
    expected = {f'reference/reference-{i}'+Path(item['path']).suffix.lower()
                for i, (_name, item) in enumerate(sorted(references.items()))}
    if not expected <= cited:
        raise ValueError('cross_view evidence must cite ALL supplied public reference views: '+str(sorted(expected-cited)))


def recover_completed_judgment(output, spec, references, image_sha256):
    """Commit a fully recorded first response after a local scoring crash.

    Does not make another model call or look for a higher score. Only the last
    in-flight attempt with a completed unmodified execution may be replayed.
    """
    output = Path(output)
    if not (output/'run.json').is_file():
        return
    previous = read_json(output/'run.json')
    attempts = previous.get('attempts', [])
    if previous.get('accepted_attempt') or not attempts or 'status' in attempts[-1]:
        return
    number = attempts[-1]['attempt']; directory = output/f'attempt-{number}'
    if not (directory/'execution.json').is_file() or not (directory/'response.json').is_file():
        return
    execution = read_json(directory/'execution.json')
    if execution.get('returncode') != 0 or execution.get('timed_out') or execution.get('modified_inputs'):
        return
    packet = output/'packet'; manifest = read_json(packet/'manifest.json')
    if sha256(packet/'manifest.json') != previous['packet_sha256']:
        raise ValueError('Interrupted judge packet changed')
    verify_packet(packet, manifest)
    for path, expected in previous['source_bindings'].items():
        if sha256(Path(path)) != expected:
            raise ValueError('Interrupted judge source changed')
    response = read_json(directory/'response.json')
    if references:
        require_reference_coverage(response, references)
    paths = verified_evidence(manifest, directory/'generated' if previous['mode']=='interactive' else None)
    judgment = score(response,spec,paths)
    if judgment.get('localization'):
        judgment['localization']['image_sha256'] = image_sha256
    attempts[-1].update(status='accepted', execution=execution, local_recovery='Replayed first recorded response after scorer crash; no new call')
    write_json(output/'issues.json',response); write_json(output/'score.json',judgment)
    write_json(output/'run.json',{**judgment,**previous,'status':'scored','S_vlm':judgment['S_vlm'],
        'summary':response['summary'],'checks':response['checks'],'issues':response.get('issues',[]),
        'accepted_attempt':number,'response_sha256':sha256(output/'issues.json'),
        'score_sha256':sha256(output/'score.json'),'run_path':str(output/'run.json')})


def judge_aligned(task_root, plan, rubric_path, evidence, output, **runtime_options):
    validate_plan(plan)
    task_root, rubric_path = Path(task_root).resolve(), Path(rubric_path).resolve()
    instruction = task_root/'instruction.md'
    if sha256(instruction) != plan['sources']['instruction.md']:
        raise ValueError('Task instruction differs from the frozen alignment plan')
    spec = read_json(rubric_path)
    if not plan.get('vlm_spec_digest') or digest(spec) != plan['vlm_spec_digest']:
        raise ValueError('Judge rubric differs from the frozen alignment plan')
    expected_family = 'Brief2Scene' if plan['profile'] == BRIEF else 'Reference2Scene'
    if spec['case_id'] != plan['task_id'] or spec['family'] != expected_family or spec['instruction_sha256'] != contract_hash(instruction.read_text()):
        raise ValueError('L1 rubric identity mismatch')
    artifacts = evidence.get('artifacts', {})
    for name in ('main.png', 'alternate.png', 'scene.blend'):
        item = artifacts.get(name, {})
        if not item.get('path') or sha256(Path(item['path'])) != item.get('sha256'):
            raise ValueError('Missing independently audited native scene/color render: '+name)
    references = {}
    if plan['profile'] != BRIEF:
        annotation = spec.get('localization')
        if not plan.get('reference_boxes') or digest(annotation) != plan['reference_boxes']:
            raise ValueError('Frozen reference box/rubric mismatch')
        name = plan['reference_primary']
        if sha256(task_root/name) != plan['sources'][name]:
            raise ValueError('Public reference changed')
        # Explicit numbered keys keep the primary first despite runtime sorting.
        views = plan.get('reference_views', [name])
        if not views or views[0] != name or len(set(views)) != len(views):
            raise ValueError('Primary-first distinct reference list required')
        for index, view in enumerate(views):
            file = (task_root/view).resolve(strict=True)
            if not file.is_relative_to(task_root/'environment/input') or sha256(file) != plan['sources'].get(view):
                raise ValueError('Unbound or nonpublic reference view')
            references[f'{index:02d}'] = {'path': str(file), 'sha256': plan['sources'][view]}
    frozen = {'_vlm_judge': {'version': 'l2-vlm-judge-v2', 'spec': spec,
                           'spec_sha256': sha256(rubric_path),
                           'mode': 'interactive' if plan['profile'] == BRIEF or plan.get('strict_reference_evidence') else 'visual'}}
    if plan.get('strict_reference_evidence'):
        inner = runtime_options.pop('invoke', run_codex)
        def strict_invoke(packet, directory, **options):
            execution = inner(packet, directory, **options)
            if execution.get('returncode') == 0 and not execution.get('timed_out'):
                require_reference_coverage(read_json(Path(directory)/'response.json'), references)
            return execution
        runtime_options['invoke'] = strict_invoke
    # In particular do not pass reference_target.scene for Text2Code.
    recover_completed_judgment(output,spec,references if plan.get('strict_reference_evidence') else {},artifacts['main.png']['sha256'])
    result = judge_task(task_root, {**evidence, 'reference_images': references}, frozen,
                        output, **runtime_options)
    result['image_sha256'] = artifacts['main.png']['sha256']
    result['annotation_sha256'] = plan.get('reference_boxes')
    result['vlm_spec_digest'] = digest(spec)
    result['alignment_plan_sha256'] = digest(plan)
    if result.get('status') == 'scored' and plan.get('strict_reference_evidence'):
        require_reference_coverage(read_json(Path(output)/'issues.json'), references)
    return result
