"""Opt-in continuous fidelity: fixed coverage and stronger deviation sensitivity."""
from copy import deepcopy

from . import task_continuous

PROTOCOL = '3dbench-strict-continuous-v1'
PROMPT = task_continuous.PROMPT.replace('q=c*(1-e)', 'q=c*(1-e)^2') + '''
STRICT REFERENCE FIDELITY CONTRACT:
Coverage uses ALL identifying features explicitly listed in each frozen question as its denominator.
First enumerate the implemented features and missing features in achieved/discrepancies, then estimate
their coverage. A box, sphere, colour patch, outline, label, or generic category resemblance earns
coverage only for the actual reference structure it demonstrates. Object presence alone cannot
establish complete feature coverage. Do not replace a missing specific feature with an invented one.
Deviation measures the implemented features' actual departure from the reference: profile, curvature,
anatomical/architectural proportions, connected shape, local relief, texture scale and spatial relations.
Describe the largest deviation explicitly. Large shape distortion must produce a correspondingly
large continuous deviation. Do not convert an old 0..4 grade or round everything into quarter steps.
The program squares the remaining fidelity (1-e); report the observed deviation without compensating
for this formula. No predetermined absolute score, model ranking, or score gap is requested.
Reference sculpture identity includes specific anatomy and sculpted detail. A generic white head or
metal horse gets credit only for the corresponding correctly reconstructed features. Similar colour
does not demonstrate anatomy. Repeated primitive curls or disconnected spheres do not demonstrate
the reference's continuous facial/neck/mane surfaces.
Reference scenes require the particular buildings, furniture and objects, their distinctive shape,
visible subparts, distribution and relationships. Repeated generic blocks and empty surfaces leave
the unmet reference content in the denominator. Do not shrink the denominator to generated objects.
For L2 public photo tasks compare every supplied corresponding view. Inspect objects, visible small
contents, material patterns, occlusion and foreground/background relationships. Respect explicitly
allowed motion changes, omitted people/text and simplifications; do not invent hidden requirements.
Material evaluation compares spatial colour distribution, texture scale, surface variation, reflection
and roughness on the corresponding objects. Similar mean colour establishes only that property.
Cross-view checks require the reference-visible geometry and relative placement to agree; merely
having a nonempty 3D scene is insufficient. Neutral diagnostic renders establish shape only.
Native tools are available to resolve uncertain visible structure; use them when needed. Preserve
authored camera/framing errors in the appropriate criterion. No candidate-fitted alignment.
'''


def legacy(spec):
    value = deepcopy(spec)
    value['protocol'] = task_continuous.PROTOCOL
    return value


def validate_spec(spec):
    if spec.get('protocol') != PROTOCOL:
        raise ValueError('Wrong strict continuous protocol')
    task_continuous.validate_spec(legacy(spec))
    return spec


def response_schema(spec, evidence_paths):
    validate_spec(spec)
    schema = task_continuous.response_schema(legacy(spec), evidence_paths)
    schema['properties']['protocol']['enum'] = [PROTOCOL]
    return schema


def verify_packet_inputs(spec, manifest):
    validate_spec(spec)
    task_continuous.verify_packet_inputs(legacy(spec), manifest)


def score(response, spec, evidence_paths):
    validate_spec(spec)
    if response.get('protocol') != PROTOCOL:
        raise ValueError('Old judgments cannot be silently relabelled as strict')
    answer = deepcopy(response)
    answer['protocol'] = task_continuous.PROTOCOL
    result = task_continuous.score(answer, legacy(spec), evidence_paths)
    weights = {c['id']: c['global_weight'] for c in spec['checks']}
    values = {}
    for row in result['criteria']:
        value = row['coverage'] * (1 - row['deviation']) ** 2
        values[row['check_id']] = value
        row.update(score=value, total_contribution_points=100 * weights[row['check_id']] * value)
    result.update(protocol=PROTOCOL, criterion_scores=values,
                  S_vlm=sum(weights[k] * v for k, v in values.items()) / sum(weights.values()),
                  score_rule='coverage * (1 - deviation)^2; fixed criterion population; no bins')
    return result
