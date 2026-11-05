"""Saved native light properties, independent of rendered image similarity."""
from __future__ import annotations

import math
import numpy as np
from scipy.spatial.transform import Rotation


def ratio(value, target):
    if value is None or target is None:
        return 0.
    a, b = float(value), float(target)
    if not math.isfinite(a) or not math.isfinite(b) or min(a, b) < 0:
        return 0.
    return 1. if max(a, b) <= 1e-12 else min(a, b) / max(a, b)


def proximity(value, target, tolerance):
    try:
        a, b = np.asarray(value, float), np.asarray(target, float)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            return 0.
        return float(np.exp(-np.linalg.norm(a - b) / tolerance))
    except (ValueError, TypeError):
        return 0.


def orientation(value, target):
    try:
        if np.shape(value) != (3,) or np.shape(target) != (3,):
            return 0.
        delta = Rotation.from_euler('xyz', value).inv() * Rotation.from_euler('xyz', target)
        return float(np.exp(-delta.magnitude() / math.radians(10)))
    except (ValueError, TypeError):
        return 0.


def backgrounds(scene):
    tree = (scene.get('world_data') or {}).get('nodes') or {}
    nodes = tree.get('nodes', {})
    # Only nodes that can reach the active World Output count as illumination.
    active = {n for n, v in nodes.items() if v['type'] == 'ShaderNodeOutputWorld'
              and v.get('properties', {}).get('is_active_output', True)}
    reachable = set(active)
    for _ in nodes:
        reachable.update(link[0] for link in tree.get('links', []) if link[2] in reachable)
    result = {}
    for name, node in nodes.items():
        if name not in reachable or node['type'] != 'ShaderNodeBackground':
            continue
        if any(link[2] == name and link[3] == 'Strength' for link in tree.get('links', [])):
            raise ValueError('Linked World Strength requires a separately supported attribute evaluator')
        values = dict(node['inputs'])
        result[name] = values.get('Strength')
    return result


def light_properties(candidate, baseline, reference, *, world_strength=False):
    """Original object identity is public in lighting tasks; missing lights score zero."""
    a, initial, goal = [x['scene'] for x in (candidate, baseline, reference)]
    lights = goal.get('light_data', {})
    if set(lights) != set(initial.get('light_data', {})):
        raise ValueError('Reference light inventory differs from the supplied initial scene')
    rows, groups = [], {}
    for name, light in lights.items():
        wanted = light['settings']; actual = a.get('light_data', {}).get(name, {}).get('settings', {})
        same_type = actual.get('type') == wanted.get('type')
        for field in ('energy', 'color'):
            if field not in wanted:
                raise ValueError('Reference light attribute missing: ' + field)
            score = (ratio(actual.get(field), wanted[field]) if field == 'energy'
                     else proximity(actual.get(field), wanted[field], .25 * math.sqrt(3))) if same_type else 0.
            rows.append({'object': name, 'property': field, 'reference': wanted[field],
                         'actual': actual.get(field), 'score': score, 'same_type': same_type})
    for field in ('energy', 'color'):
        selected = [r['score'] for r in rows if r['property'] == field]
        if selected:
            groups[field] = float(np.mean(selected))
    if world_strength:
        targets = backgrounds(goal)
        if not targets or set(targets) != set(backgrounds(initial)):
            raise ValueError('Reference and initial need matching active World Background nodes')
        try:
            actual = backgrounds(a)
        except ValueError:
            actual = {}
        values = []
        for name, value in targets.items():
            if value is None or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid reference World Strength')
            score = ratio(actual.get(name), value); values.append(score)
            rows.append({'object': 'World/' + name, 'property': 'strength',
                         'reference': value, 'actual': actual.get(name), 'score': score})
        groups['world_strength'] = float(np.mean(values))
    if not groups:
        raise ValueError('Lighting target has no editable light or World attribute')
    return {'status': 'measured', 'score': float(np.mean(list(groups.values()))),
            'groups': groups, 'properties': rows, 'light_count': len(lights),
            'comparison': 'Native energy ratio and linear RGB distance; no image score',
            'threshold_status': 'pilot_not_calibrated'}


def fixed_light_properties(before, after, *, allow_color_energy):
    old, new = before.get('light_data', {}), after.get('light_data', {})
    rows = []
    for name in sorted(set(old) | set(new)):
        wanted = old.get(name, {}).get('settings', {}); actual = new.get(name, {}).get('settings', {})
        ob, oa = before['objects'].get(name, {}), after['objects'].get(name, {})
        values = {'inventory': float(name in old and name in new)}
        if name in old and name in new:
            values.update(type=float(wanted['type'] == actual.get('type')),
                          position=proximity(oa.get('location'), ob.get('location'), .05),
                          orientation=orientation(oa.get('rotation'), ob.get('rotation')),
                          scale=proximity(oa.get('scale'), ob.get('scale'), .05),
                          visibility=float(oa.get('visible_render') == ob.get('visible_render')))
            fields = {'AREA': ['size', 'size_y'], 'POINT': ['shadow_soft_size'],
                      'SUN': ['angle'], 'SPOT': ['shadow_soft_size', 'spot_size', 'spot_blend']}.get(wanted['type'], [])
            for field in fields:
                if field in wanted:
                    values[field] = ratio(actual.get(field), wanted[field])
            if wanted['type'] == 'AREA':
                values['shape'] = float(actual.get('shape') == wanted.get('shape'))
            for field in ('exposure', 'normalize', 'use_nodes'):
                if field in wanted:
                    values[field] = float(actual.get(field) == wanted[field])
            # Nodes, constraints and all other RNA settings cannot silently bypass energy.
            ignored = {'color', 'energy'} if allow_color_energy else set()
            handled = set(fields) | {'type', 'shape', 'exposure', 'normalize', 'use_nodes'} | ignored
            values['other_settings'] = float({k:v for k,v in actual.items() if k not in handled} ==
                                             {k:v for k,v in wanted.items() if k not in handled})
            values['nodes'] = float(old[name].get('nodes') == new[name].get('nodes'))
            values['constraints'] = float(oa.get('constraints_sha256') == ob.get('constraints_sha256'))
            if not allow_color_energy:
                values['energy'] = ratio(actual.get('energy'), wanted.get('energy'))
                values['color'] = proximity(actual.get('color'), wanted.get('color'), .25 * math.sqrt(3))
        rows.append({'object': name, 'properties': values, 'score': float(np.mean(list(values.values())))})
    return {'status': 'measured', 'score': float(np.mean([r['score'] for r in rows])) if rows else None,
            'lights': rows}
