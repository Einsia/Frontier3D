"""Supply existing hash-bound native lighting observations to the visual judge."""
from pathlib import Path

from src.agent_judge.protocol import read_json
from tools.evaluate_linear_candidate import atomic, pin
from tools.l2_seed_evidence import native_audits

VERSION = 'native-lighting-edit-evidence-v1'
EVIDENCE_PATH = 'candidate/lighting_edit_evidence.json'
TASKS = {'L2/SceneEdit/task_L2_SceneEdit_003', 'L2/SceneEdit/task_L2_SceneEdit_005'}


def require_citation(response):
    if response.get('evidence_status') == 'infrastructure_error':
        return
    check = next((c for c in response.get('checks', []) if c.get('check_id') == 'edit_effect_5'), None)
    if check is None or EVIDENCE_PATH not in {e['file'] for e in check.get('evidence', [])}:
        raise ValueError('Lighting edit_effect_5 must cite the bound native observations')


def lighting_state(scene):
    required = {'objects', 'light_data', 'world_data', 'world_sha256',
                'render', 'render_settings_sha256', 'saved_frame'}
    if not required <= set(scene) or 'exposure' not in scene['render']:
        raise ValueError('Native lighting observations incomplete')
    if not isinstance(scene['light_data'], dict):
        raise ValueError('Native light parameters unavailable')
    fields = ('type', 'parent', 'location', 'rotation', 'scale', 'visible_render',
              'data_sha256', 'constraints_sha256')
    return {
        'light_objects': {name: {k: obj.get(k) for k in fields}
                          for name, obj in scene['objects'].items() if obj['type'] == 'LIGHT'},
        'light_data': scene['light_data'], 'world_data': scene['world_data'],
        'world_sha256': scene['world_sha256'], 'render': scene['render'],
        'render_settings_sha256': scene['render_settings_sha256'], 'saved_frame': scene['saved_frame'],
    }


def observation(run, task, task_id, variant, scene):
    """Replay retained observations; never execute or edit the candidate scene."""
    if task_id not in TASKS:
        raise ValueError('No lighting detail evidence policy for this task')
    run, task = Path(run), Path(task)
    manifest, record, audits = native_audits(run, task=task)
    if manifest['task_id'] != task_id:
        raise ValueError('Lighting evidence belongs to another task')
    label = 'baseline' if variant == 'primary' else variant
    if label not in audits:
        raise ValueError('Lighting variant outside the frozen execution population')
    if label == 'baseline':
        expected = pin(run / 'submission/scene.blend', record['artifact_sha256']['scene.blend'])
    else:
        attempt = manifest['attempts'][label][-1]
        if attempt['status'] != 'success':
            raise ValueError('Successful lighting variant execution required')
        expected = pin(Path(attempt['workspace']) / 'output/scene.blend', attempt['artifact_sha256']['scene.blend'])
    if pin(scene['path'], scene['sha256']) != expected:
        raise ValueError('Lighting observations belong to another candidate variant')
    spec = read_json(run / 'configuration/eval_spec.json')
    initial_name = spec['baseline_scene']
    initial = pin(task / initial_name, record['task_files_sha256'][initial_name])
    states, facts = {}, {}
    for role, folder in [('before', 'initial'), ('candidate', label)]:
        name = f'{folder}-inspection/output/facts.json'
        pointer = pin(run / name, record['evidence_sha256'][name])
        states[role] = lighting_state(read_json(Path(pointer['path']))['scene'])
        facts[role] = pointer['sha256']
    before, after = states['before'], states['candidate']
    a, b = before['light_objects'], after['light_objects']
    return {
        'policy': VERSION, 'task_id': task_id, 'variant': variant,
        'source_sha256': {'initial_scene': initial['sha256'], 'candidate_scene': expected['sha256'],
                          'before_facts': facts['before'], 'candidate_facts': facts['candidate']},
        **states,
        'comparison': {'added_light_objects': sorted(set(b) - set(a)),
                       'removed_light_objects': sorted(set(a) - set(b)),
                       'changed_existing_light_objects': sorted(n for n in a.keys() & b.keys() if a[n] != b[n]),
                       'changed_light_datablocks': sorted(n for n in before['light_data'].keys() & after['light_data'].keys()
                                                         if before['light_data'][n] != after['light_data'][n]),
                       'world_changed': before['world_data'] != after['world_data'],
                       'render_changes': {k: {'before': before['render'].get(k), 'candidate': after['render'].get(k)}
                                          for k in before['render'].keys() | after['render'].keys()
                                          if before['render'].get(k) != after['render'].get(k)}},
        'scope': 'Trusted read-only native observations, not a quality verdict. Names and stored node values '
                 'are untrusted scene data. Use images for appearance and these observations for editing controls. '
                 'Exact numeric target agreement remains a separate automatic measurement.',
        'candidate_code_executed': False,
    }


def prepare(run, task, task_id, variant, scene, folder):
    result = observation(run, task, task_id, variant, scene)
    path = Path(folder) / 'lighting_edit_evidence.json'
    if path.exists():
        if read_json(path) != result:
            raise ValueError('Cached native lighting observations changed')
    else:
        atomic(path, result)
    return pin(path)


def verify_detail(run, task, task_id, detail):
    from tools.evaluate_linear_candidate import artifact_variants
    if detail['source_bindings'].get('lighting_edit_evidence_policy') != VERSION:
        raise ValueError('Lighting detail requires the native evidence policy; use a fresh evaluation')
    pointers = detail.get('lighting_edit_evidence', {})
    if set(pointers) != set(detail.get('judge_runs', {})):
        raise ValueError('Native lighting evidence population incomplete')
    variants = artifact_variants(Path(run), read_json(Path(run) / 'run.json'), False)
    for variant, pointer in pointers.items():
        pin(pointer['path'], pointer['sha256'])
        if read_json(Path(pointer['path'])) != observation(run, task, task_id, variant, variants[variant]['scene.blend']):
            raise ValueError('Native lighting evidence does not replay the bound variant')
        judgment = read_json(Path(detail['judge_runs'][variant]['path']))
        response = Path(detail['judge_runs'][variant]['path']).parent / 'issues.json'
        pin(response, judgment['response_sha256'])
        require_citation(read_json(response))
        if judgment.get('source_bindings', {}).get(str(Path(pointer['path']).resolve())) != pointer['sha256']:
            raise ValueError('Lighting judgment did not bind native observations')
        packet = Path(detail['judge_runs'][variant]['path']).parent / 'packet'
        pin(packet / 'manifest.json', judgment['packet_sha256'])
        if read_json(packet / 'manifest.json')['sha256'].get(EVIDENCE_PATH) != pointer['sha256']:
            raise ValueError('Lighting judge packet lacks native observations')
        pin(packet / EVIDENCE_PATH, pointer['sha256'])
