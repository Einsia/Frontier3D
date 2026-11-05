"""Apply public L2 texture rules to retained, hash-bound inspections."""
import os
from benchmark.resources import resource, blender_path, env_path, judge_key, judge_model, read_public_methods

import re

from pathlib import Path

from src.agent_judge.protocol import read_json as read

from tools.evaluate_linear_candidate import pin

from src.evaluator.l1_edit_validity import combine

VERSION = 'l2-public-material-validity-v1'

def texture_allowed(instruction):
    if re.search(r'(?:no|without|forbid\w*|prohibit\w*)[^.\n]{0,60}(?:image textures?|texture images?)', instruction, re.I):
        return False
    return ('Local material textures are allowed.' in instruction
            or 'using local texture or shallow relief' in instruction
            or ('pack textures' in instruction.lower()
                and 'no evaluator-only constraint' in instruction.lower()))

def reference_usage_status(usage, allowed):
    """Accept stored references and proven local UV crops, never whole-frame use."""
    if usage.get('protocol') not in {'reference-texture-usage-v2','reference-texture-usage-v3'} or not usage.get('source_unchanged'):
        raise ValueError('Reference usage proof incomplete')
    if usage['unaccounted_reference_images'] or usage.get('unaccounted_reference_nodes'):
        raise ValueError('Reference usage needs world/group/compositor review')
    active=[r for r in usage['uses'] if r['linked_to_active_output'] and not r['muted']]
    if not active:return 'passed','reference_retained_without_render_use'
    if not allowed:return 'failed','reference_texture_not_permitted'
    for row in active:
        if not row.get('uv_supported') or 'uv_area' not in row:
            raise ValueError('Reference texture coordinate mapping unresolved')
        if (any(v < -1e-6 for v in row['uv_min']) or any(v > 1+1e-6 for v in row['uv_max'])
                or not 0 < row['uv_area']):
            raise ValueError('Reference texture UV wrapping/degeneracy requires review')
        if row['uv_area']>=1-1e-6:
            if row.get('object_type')=='MESH' and row.get('polygons',3)<=2 and row.get('vertices',5)<=4:
                return 'failed','complete_reference_on_plane'
            raise ValueError('Whole reference on volumetric geometry requires semantic review')
        if row['uv_area']>.5:raise ValueError('Large reference crop requires semantic review')
    return 'passed','public_local_reference_crops'

def scene_status(scene, allowed, references, *, reference_usage=None):
    inventory = scene.get('procedural_materials', {})
    if type(inventory.get('passed')) is not bool:
        raise ValueError('Material inventory unresolved')
    if references and 'used_packed_image_sha256' not in scene:
        raise ValueError('Reference-image dependency inventory unresolved')
    reused = sorted(set(scene.get('used_packed_image_sha256', [])) & set(references))
    reference_reason=None
    if reused:
        if reference_usage is not None:
            status,reason=reference_usage_status(reference_usage,allowed)
            if status=='failed':return status,reason,reused
            reference_reason=reason
        else:return 'failed', 'complete_reference_image_reused', reused
    if inventory['passed']:
        return 'passed', reference_reason or 'procedural_materials', reused
    violations = inventory.get('violations', [])
    permitted = bool(violations) and all(
        v['kind'] in {'image_datablock', 'image_node'}
        and (v['owner'].startswith('material:') or v['owner'].startswith('world:'))
        and (v['kind'] != 'image_node' or v['name'] in {'ShaderNodeTexImage', 'ShaderNodeTexEnvironment'})
        for v in violations)
    return ('passed', reference_reason or 'public_local_texture_permission', reused) if allowed and permitted else (
        'failed', 'image_use_not_covered_by_public_permission', [])

def measure(source, plan):
    instruction = plan['instruction']
    pin(instruction['path'], instruction['sha256'])
    allowed = texture_allowed(Path(instruction['path']).read_text())
    references = {r['sha256'] for r in plan['references']}
    for pointer in plan['references']:
        pin(pointer['path'], pointer['sha256'])
    results = {}
    for seed in ('primary', 'seed-0', 'seed-1', 'seed-2'):
        receipt_path = source / 'legacy_reproducibility' / seed / 'receipt.json'
        receipt = read(receipt_path)
        pointer = receipt['facts']
        pin(pointer['path'], pointer['sha256'])
        scene_pointer = receipt['source_bindings']['scene']
        pin(scene_pointer['path'], scene_pointer['sha256'])
        scene = read(Path(pointer['path']))['scene']
        usage=None;usage_pointer=None
        if references & set(scene.get('used_packed_image_sha256', [])):
            from tools.reference_texture_usage import collect
            usage,usage_pointer=collect(scene_pointer,references,source/'reference_usage'/seed)
        status, reason, reused = scene_status(scene, allowed, references,reference_usage=usage)
        results[seed] = dict(measurement_status=status, reason=reason,
            reused_reference_sha256=reused, receipt=pin(receipt_path), facts=pointer,
            original_procedural_passed=scene['procedural_materials']['passed'],reference_usage=usage_pointer)
    return dict(policy=VERSION, instruction=instruction, references=plan['references'],
        local_textures_allowed=allowed, per_variant=results,
        measurement_status=combine(r['measurement_status'] for r in results.values()))
