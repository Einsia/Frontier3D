"""Exclude only the exact organizer daylight sky from solid-scene measurements."""
import copy
from .protocol import read_json, digest

SKY_MATERIAL = '/Game/L3Environment/M_DefaultSky.M_DefaultSky'
SKY_SIGNATURE = {
    'mesh': '/Engine/BasicShapes/Sphere.Sphere',
    'materials': [SKY_MATERIAL], 'origin_cm': [0, 0, 0],
    'axis_x': [5000, 0, 0], 'axis_y': [0, 5000, 0], 'axis_z': [0, 0, 5000],
    'collision_enabled': False, 'blocks_pawn': False,
}


def physical_scene(exported, trial):
    result = copy.deepcopy(exported)
    audit = {'policy': 'exact_organizer_sky_runtime_signature_v2', 'excluded': [],
             'scope': 'No wildcard actor, non-colliding-mesh, or material-only exclusion.'}
    if trial is None:
        audit['status'] = 'no_equipment_provenance'
        return result, audit
    hashes = read_json(trial/'preflight-complete.json')['input_and_material_hashes']
    required = ['project/Content/L3Environment/M_DefaultSky.uasset']
    valid = all(hashes.get(name) and (trial/'workspace'/name).is_file()
                and digest(trial/'workspace'/name) == hashes[name] for name in required)
    if not valid:
        audit['status'] = 'organizer_background_modified_or_unverified'
        return result, audit
    audit['equipment_hashes'] = {name: hashes[name] for name in required}
    header='project/Source/L3Environment/L3DefaultEnvironment.h'
    audit['daylight_helper_changed'] = not (hashes.get(header) and (trial/'workspace'/header).is_file()
                                           and digest(trial/'workspace'/header)==hashes[header])
    audit['provenance_rule'] = 'Unchanged organizer sky material plus exact observed mesh, transform and collision signature; unrelated lighting edits do not turn the sky into a solid.'
    kept = []
    for item in result['instances']:
        if all(item.get(key) == value for key, value in SKY_SIGNATURE.items()):
            audit['excluded'].append({'actor': item['actor'], 'component': item['component'],
                                      'instance': item['instance'], 'reason': 'Exact unchanged organizer nonphysical sky'})
        else:
            kept.append(item)
    result['instances'] = kept
    audit['status'] = 'applied'
    audit['input_instances'] = len(exported['instances'])
    audit['physical_instances'] = len(kept)
    return result, audit
