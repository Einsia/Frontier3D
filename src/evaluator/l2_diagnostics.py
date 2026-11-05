"""Measured scene diagnostics; role claims and tolerances do not prove semantics."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .l2_metrics import entities


def support_graph(groups, tolerance=.02, max_triangles=250000):
    """Sampled vertical contacts, including partial/no coverage and penetrations."""
    import time
    deadline = time.monotonic()+8
    edges, measurements = [], []
    for entity in groups:
        points = [p for _, o in entity['members'] for p in o.get('support_points', [])
                  if p[2] <= entity['low'][2]+.02]
        points = points[::max(1, int(np.ceil(len(points)/64)))]
        samples = []
        truncated = False
        for point in points:
            if time.monotonic() > deadline:
                truncated = True
                break
            hits = []
            for support in groups:
                if support['id'] == entity['id'] or np.any(np.asarray(point[:2]) < support['low'][:2]) or np.any(np.asarray(point[:2]) > support['high'][:2]):
                    continue
                # A higher unrelated object is not a support underneath this entity.
                if support['low'][2] > point[2]+tolerance:
                    continue
                raw = [t for _, o in support['members'] for t in o.get('surface_triangles', [])]
                if len(raw) > max_triangles:
                    truncated = True
                    continue
                if not raw:
                    continue
                tri = np.asarray(raw, dtype=float)
                a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
                v0, v1, v = b-a, c-a, np.asarray(point)-a
                den = v0[:, 0]*v1[:, 1]-v0[:, 1]*v1[:, 0]
                valid = np.abs(den) > 1e-12
                safe = np.where(valid, den, 1)
                u = (v[:, 0]*v1[:, 1]-v[:, 1]*v1[:, 0])/safe
                w = (v0[:, 0]*v[:, 1]-v0[:, 1]*v[:, 0])/safe
                valid &= (u >= -1e-7) & (w >= -1e-7) & (u+w <= 1+1e-7)
                heights = (a[:, 2]+u*v0[:, 2]+w*v1[:, 2])[valid]
                # Retain small penetrations; deep overlaps are separately diagnosed.
                heights = heights[heights <= point[2]+max(.5, tolerance)]
                if len(heights):
                    hits.append((float(max(heights)), support['id']))
            if hits:
                height, owner = max(hits)
                gap = float(point[2]-height)
                samples.append({'point': point, 'support': owner, 'gap_m': gap})
                if abs(gap) <= tolerance:
                    edges.append((owner, entity['id']))
            else:
                samples.append({'point': point, 'support': None, 'gap_m': None})
        gaps = [s['gap_m'] for s in samples if s['gap_m'] is not None]
        contact = sum(abs(g) <= tolerance for g in gaps)
        measurements.append({'entity': entity['id'], 'role': entity['role'], 'samples': samples,
            'sample_count': len(samples), 'covered_count': len(gaps), 'contact_count': contact,
            'contact_fraction': contact/len(samples) if samples else None,
            'min_gap_m': min(gaps) if gaps else None, 'max_gap_m': max(gaps) if gaps else None,
            'status': 'incomplete' if truncated or not samples else 'measured',
            'floating_suspect': bool(gaps) and min(gaps) > tolerance,
            'penetration_suspect': bool(gaps) and min(gaps) < -tolerance})
    return {'contact_tolerance_m': tolerance, 'diagnostic_only': True,
        'edges': [{'support': a, 'supported': b} for a, b in sorted(set(edges))],
        'entities': measurements,
        'limitations': ['Sampled vertical contacts do not prove static stability or load capacity.',
            'Deep containment, lateral support and intentional joints need mesh evidence and human review.']}


def scene_diagnostics(evidence, *, entity_parts=None, include_support=True):
    scene = evidence.get('scene', {})
    objects = scene.get('objects', {})
    roles = sorted({o.get('role') for o in objects.values() if o.get('role')})
    groups = [dict(e, role=role) for role in roles for e in entities(evidence, role)]
    inventory = []
    for e in groups:
        parts = sorted({o['part'] for _, o in e['members'] if o.get('part')})
        inventory.append({'id': e['id'], 'claimed_role': e['role'], 'bounds': [e['low'].tolist(), e['high'].tolist()],
            'dimensions_m': e['dimensions'].tolist(), 'parts': parts,
            'missing_parts': sorted(set((entity_parts or {}).get(e['role'], ()))-set(parts)),
            'members': [n for n, _ in e['members']], 'mesh_count': len(e['members']),
            'material_names': sorted({m for _, o in e['members'] for m in o.get('materials', [])}),
            'semantic_status': 'pending_human', 'volume_sum_m3': e['volume']})
    return {'schema_version': 1, 'diagnostic_only': True, 'entities': inventory,
        'untagged_meshes': [n for n, o in objects.items() if o.get('type') == 'MESH' and o.get('visible_render') and not o.get('role')],
        'entity_projections': scene.get('entity_projections', {}),
        'cameras': scene.get('cameras', {}), 'render': scene.get('render', {}),
        'support': support_graph(groups) if include_support else {'status': 'not_requested'},
        'mesh_contacts': scene.get('mesh_contacts', {'status': 'missing', 'pairs': []}),
        'limitations': ['Entity roles and part names are untrusted author claims, checked against measured meshes.',
                       'Category recognition, designed contacts and material appearance require review.']}


def draw_scene(data, path):
    inventory = data['entities']
    if not inventory:
        return
    low = np.min([e['bounds'][0][:2] for e in inventory], axis=0)
    high = np.max([e['bounds'][1][:2] for e in inventory], axis=0)
    extent = np.maximum(high-low, .01)
    image = Image.new('RGB', (1000, 800), 'white')
    draw = ImageDraw.Draw(image)
    def xy(p):
        q = (np.asarray(p[:2])-low)/extent
        return (40+q[0]*650, 730-q[1]*650)
    suspects = {e['entity'] for e in data['support'].get('entities', []) if e['floating_suspect'] or e['penetration_suspect']}
    for i, entity in enumerate(inventory):
        a, b = (xy(p) for p in entity['bounds'])
        color = '#c22' if entity['id'] in suspects else '#2473a8'
        draw.rectangle((a[0], b[1], b[0], a[1]), outline=color, width=2)
        draw.text((a[0]+2, b[1]+2), str(i+1), fill=color)
        if i < 45:
            draw.text((720, 36+i*16), f"{i+1}: {entity['claimed_role']}"[:42], fill=color)
    draw.text((30, 16), 'Measured XY bounds (metres). Red: sampled support warning; overlap is not proof of collision.', fill='black')
    image.save(path)


def write_diagnostics(evidence, directory, *, entity_parts=None, route_check=None, spec=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    data = scene_diagnostics(evidence, entity_parts=entity_parts)
    draw_scene(data, directory/'scene_diagnostics.png')
    if route_check is not None:
        from .l2_metrics import traversable_route
        try:
            _, result = traversable_route(route_check, evidence, spec, diagnostic_directory=directory)
            data['route'] = result
        except ValueError as error:
            data['route'] = {'status': 'unavailable', 'reason': str(error)}
    (directory/'scene_diagnostics.json').write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    return data


def write_route(directory, road, blocked, usable, radius, origin, cell, start_labels, goal_labels, components):
    colors = np.full((*road.shape, 3), 238, dtype=np.uint8)
    colors[road] = [155, 155, 155]
    colors[road & blocked] = [220, 65, 65]
    colors[usable] = [65, 150, 100]
    colors[np.isin(components, list(start_labels)) & usable] = [60, 120, 220]
    image = Image.fromarray(colors[::-1])
    image.thumbnail((1400, 1400))
    if max(image.size) < 600:
        image = image.resize((image.width*3, image.height*3), Image.Resampling.NEAREST)
    canvas = Image.new('RGB', (max(720, image.width), image.height+60), 'white')
    canvas.paste(image, (0, 60))
    draw = ImageDraw.Draw(canvas)
    draw.text((10, 8), 'Road: gray. Blocked: red. Required clearance: green. Reachable from entrance: blue.', fill='black')
    draw.text((10, 28), f'Grid {cell:g} m; +Y up. Raster clearance is approximate, not a physical stability test.', fill='black')
    canvas.save(Path(directory)/'road_diagnostics.png')
    np.savez_compressed(Path(directory)/'road_grid.npz', road=road, blocked=blocked, usable=usable,
                        clearance_radius=radius, origin=origin, cell_size=cell, components=components)
