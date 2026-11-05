"""Trusted compact geometry/property inspector and exact-triangle distance worker."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_bound(item):
    path = Path(item['path'])
    if digest(path) != item['sha256']: raise ValueError('Bound evidence changed: ' + str(path))
    return path


def pointer(path):
    return {'path': str(path), 'sha256': digest(path)}


def mesh(item):
    path = read_bound(item)
    with np.load(path, allow_pickle=False) as data:
        vertices = data['vertices_m'].copy(); faces = data['triangles'].copy()
    return vertices, faces


def join_mesh(items):
    vertices, triangles, offset = [], [], 0
    for item in items:
        v, f = mesh(item)
        if len(f): vertices.append(v); triangles.append(f+offset); offset += len(v)
    if not vertices: return np.empty((0, 3)), np.empty((0, 3), dtype=np.int64)
    return np.concatenate(vertices), np.concatenate(triangles)


class TriangleQuery:
    def __init__(self, vertices, triangles):
        from mathutils.bvhtree import BVHTree
        from continuous_surface import triangle_areas
        v, f = np.asarray(vertices, float), np.asarray(triangles)
        area = triangle_areas(v, f)
        usable = area > 1e-18
        if not usable.any(): raise ValueError('Empty triangle query surface')
        # Both target and query points use the SAME arithmetic transform. This
        # improves BVH float precision and never changes relative coordinates.
        self.origin = (v.min(0)+v.max(0))/2
        self.scale = float(np.ptp(v, axis=0).max())
        if self.scale <= 0: raise ValueError('Degenerate query span')
        self.triangle_vertices = v[f[usable]]
        self.boxes = []
        lower, upper = self.triangle_vertices.min(1), self.triangle_vertices.max(1)
        centres = (lower+upper)/2

        def build(indices):
            low, high = lower[indices].min(0), upper[indices].max(0)
            index = len(self.boxes)
            self.boxes.append(None)
            if len(indices) <= 16:
                self.boxes[index] = (low, high, None, None, indices)
            else:
                axis = np.ptp(centres[indices], axis=0).argmax()
                middle = len(indices)//2
                order = np.argpartition(centres[indices, axis], middle)
                left, right = build(indices[order[:middle]]), build(indices[order[middle:]])
                self.boxes[index] = (low, high, left, right, None)
            return index

        build(np.arange(len(self.triangle_vertices)))
        self.tree = BVHTree.FromPolygons(((v-self.origin)/self.scale).tolist(),
                                        f[usable].tolist(), all_triangles=True, epsilon=0.)

    def nearest(self, points):
        points = np.asarray(points, float)
        if points.ndim != 2 or points.shape[1:] != (3,) or not np.isfinite(points).all():
            raise ValueError('Finite world-space query points required')
        indices = []
        for point in points:
            hit, _, index, _ = self.tree.find_nearest((point-self.origin)/self.scale)
            if hit is None: raise ValueError('Nearest triangle unavailable')
            indices.append(index)
        if not indices: return np.empty(0), np.empty((0, 3))
        # BVH chooses a triangle using float32. Recompute its closest point in
        # float64 so a point on an unchanged face does not become a false edit.
        hits = self.closest(points, self.triangle_vertices[indices])
        distances = np.linalg.norm(points-hits, axis=1)
        # Float32 nearest and nearest-range queries can both omit a thin
        # triangle containing the point. Use the BVH only for a valid upper
        # distance bound, then search float64 triangle AABBs to establish the
        # minimum over every triangle that could improve that bound.
        roundoff = 32*np.finfo(float).eps*max(self.scale, np.abs(points).max(), 1.)
        stack = [(0, np.arange(len(points)))]
        while stack:
            box, population = stack.pop()
            low, high, left, right, faces = self.boxes[box]
            offset = np.maximum(low-points[population], 0)+np.maximum(points[population]-high, 0)
            keep = np.einsum('ij,ij->i', offset, offset) <= (distances[population]+roundoff)**2
            population = population[keep]
            if not len(population): continue
            if faces is None:
                stack.extend(((left, population), (right, population)))
                continue
            for start in range(0, len(population), 4096):
                selected = population[start:start+4096]
                query = np.repeat(points[selected], len(faces), axis=0)
                xyz = np.tile(self.triangle_vertices[faces], (len(selected), 1, 1))
                candidate_hits = self.closest(query, xyz).reshape(len(selected), len(faces), 3)
                delta = candidate_hits-points[selected, None, :]
                candidate_distances = np.linalg.norm(delta, axis=2)
                chosen = candidate_distances.argmin(axis=1)
                shortest = candidate_distances[np.arange(len(selected)), chosen]
                improve = shortest < distances[selected]
                hits[selected[improve]] = candidate_hits[np.flatnonzero(improve), chosen[improve]]
                distances[selected[improve]] = shortest[improve]
        return distances, hits

    @staticmethod
    def closest(points, xyz):
        a, b, c = (xyz[:, index] for index in range(3))
        normal = np.cross(b-a, c-a)
        norm2 = np.einsum('ij,ij->i', normal, normal)
        projected = points-(np.einsum('ij,ij->i', points-a, normal)/norm2)[:, None]*normal
        barycentric = np.stack([
            np.einsum('ij,ij->i', np.cross(b-projected, c-projected), normal),
            np.einsum('ij,ij->i', np.cross(c-projected, a-projected), normal),
            np.einsum('ij,ij->i', np.cross(a-projected, b-projected), normal)], axis=1)/norm2[:, None]
        inside = (barycentric >= 0).all(axis=1)
        edge_hits = []
        for start, end in ((a, b), (b, c), (c, a)):
            edge = end-start
            factor = np.clip(np.einsum('ij,ij->i', points-start, edge)/np.einsum('ij,ij->i', edge, edge), 0, 1)
            edge_hits.append(start+factor[:, None]*edge)
        edge_hits = np.stack(edge_hits, axis=1)
        distances2 = ((edge_hits-points[:, None, :])**2).sum(axis=2)
        hits = edge_hits[np.arange(len(points)), distances2.argmin(axis=1)]
        hits[inside] = projected[inside]
        return hits


def inspect(request, output):
    import bpy
    from l2_case_blender import properties, tree_signature, normalize, render_settings
    source = read_bound(request['scene'])
    if source.suffix.lower() == '.glb':
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source))
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source), load_ui=False, use_scripts=False)
    scene = bpy.context.scene
    snapshots = []
    for index, frame in enumerate(request.get('frames', [1])):
        scene.frame_set(frame); bpy.context.view_layer.update()
        scale = float(scene.unit_settings.scale_length)
        if not np.isfinite(scale) or scale <= 0: raise ValueError('Invalid scene unit scale')
        graph = bpy.context.evaluated_depsgraph_get()
        objects, total = [], 0
        for instance in graph.object_instances:
            obj = instance.object
            original = obj.original
            if obj.hide_render: continue
            matrix = np.asarray(instance.matrix_world, dtype=float)
            world_m = matrix.copy(); world_m[:3, 3] *= scale
            item = {'object': original.name, 'type': original.type,
                'instance': bool(instance.is_instance), 'parent': original.parent.name if original.parent else None,
                'matrix_world_m': world_m.tolist(), 'scale': list(original.scale),
                'editable': original.library is None and getattr(original.data, 'library', None) is None,
                'modifiers': [m.type for m in original.modifiers],
                'constraints': [properties(c) for c in original.constraints],
                'collections': [c.name for c in original.users_collection],
                'visible_render': True, 'geometry': None}
            if obj.type in {'CAMERA', 'LIGHT'}:
                item['settings'] = properties(obj.data)
                if obj.type == 'LIGHT': item['nodes'] = tree_signature(obj.data.node_tree)
            if obj.type in {'MESH', 'CURVE', 'SURFACE', 'FONT', 'META'}:
                evaluated = obj.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
                try:
                    if evaluated is not None and len(evaluated.polygons):
                        evaluated.calc_loop_triangles()
                        total += len(evaluated.loop_triangles)
                        if total > request.get('max_triangles', 12000000):
                            raise ValueError('Complete scene exceeds declared triangle capacity')
                        vertices = np.empty(len(evaluated.vertices)*3, dtype=float)
                        evaluated.vertices.foreach_get('co', vertices)
                        vertices = (vertices.reshape(-1, 3)@matrix[:3, :3].T+matrix[:3, 3])*scale
                        faces = np.empty(len(evaluated.loop_triangles)*3, dtype=np.int64)
                        evaluated.loop_triangles.foreach_get('vertices', faces); faces = faces.reshape(-1, 3)
                        materials = np.empty(len(evaluated.loop_triangles), dtype=np.int32)
                        evaluated.loop_triangles.foreach_get('material_index', materials)
                        path = output / f'frame-{index:03d}-object-{len(objects):06d}.npz'
                        np.savez_compressed(path, vertices_m=vertices, triangles=faces, material_indices=materials)
                        item.update(geometry=pointer(path), bounds_m=[vertices.min(0).tolist(), vertices.max(0).tolist()],
                                    triangles=len(faces), vertices=len(vertices))
                        item['materials'] = []
                        for slot, material in enumerate(evaluated.materials):
                            if slot < len(obj.material_slots) and obj.material_slots[slot].link == 'OBJECT':
                                material = obj.material_slots[slot].material
                            item['materials'].append(None if material is None else {
                                'settings': properties(material), 'nodes': tree_signature(material.node_tree)})
                finally: obj.to_mesh_clear()
            objects.append(item)
        snapshots.append({'frame': frame, 'sequence_index': index, 'unit_scale': scale,
            'unit_system': scene.unit_settings.system, 'objects': objects, 'triangles': total,
            'active_camera': scene.camera.name if scene.camera else None,
            'world': None if scene.world is None else {'settings': properties(scene.world), 'nodes': tree_signature(scene.world.node_tree)},
            'render': render_settings(scene)})
    read_bound(request['scene'])
    return normalize({'protocol': 'continuous-native-inspection-v2', 'scene': request['scene'],
        'coordinate_space': 'world_metres', 'registration': 'none', 'autoexec': False,
        'source_unchanged': True, 'snapshots': snapshots})


def compare(request, output):
    from continuous_surface import area_samples, surface_raw
    sides = {name: join_mesh(items) for name, items in request['surfaces'].items()}
    queries = {k: TriangleQuery(*v) for k, v in sides.items() if len(v[1])}
    count, seed = request.get('sample_count', 32768), request.get('random_seed', 20261016)
    sampled = {k: area_samples(*v, count, seed+i)[0] for i, (k, v) in enumerate(sides.items()) if len(v[1])}
    evidence = [item for items in request['surfaces'].values() for item in items]
    if request['kind'] == 'equivalence':
        if 'candidate' not in queries or 'reference' not in queries:
            return {'equivalence': {'status': 'absent', 'evidence': evidence, 'reason': 'Required geometry absent'}}
        a = queries['reference'].nearest(sampled['candidate'])[0]
        b = queries['candidate'].nearest(sampled['reference'])[0]
        return {'equivalence': surface_raw(a, b, request['half_scale_m'], evidence,
            requested_samples=count, random_seed=seed)}
    if request['kind'] != 'edit': raise ValueError('Unknown surface comparison')
    if not {'baseline', 'reference'} <= queries.keys(): raise ValueError('Trusted edit surfaces missing')
    if 'candidate' not in queries:
        return {name: {'status': 'absent', 'evidence': evidence, 'reason': 'Candidate geometry absent'}
                for name in ('target_surface', 'protected_native')}
    tolerance = request['preserve_half_scale_m']
    scope_epsilon = request['scope_epsilon_m']
    if not np.isfinite(scope_epsilon) or not 0 < scope_epsilon < min(tolerance, request['target_half_scale_m']):
        raise ValueError('Frozen scope precision must be positive and smaller than scoring distance scales')
    # Reference and baseline alone define the edit/keep split. Candidate geometry
    # is queried in the same world coordinates and never changes that split.
    # The numeric scope precision is separate from the scoring decay scale:
    # new surfaces near a join remain part of the requested edit.
    r, b, c = (sampled[name] for name in ('reference', 'baseline', 'candidate'))
    changed_ref = queries['baseline'].nearest(r)[0] > scope_epsilon
    protected_base = queries['reference'].nearest(b)[0] <= scope_epsilon
    if not changed_ref.any() or not protected_base.any():
        raise ValueError('Frozen reference scope has no sampled edit or protected population')
    candidate_baseline_distance, _ = queries['baseline'].nearest(c)
    changed_candidate = candidate_baseline_distance > scope_epsilon
    candidate_reference_distance, candidate_reference_hit = queries['reference'].nearest(c)
    # Classify against the requested final surface. Projecting additions onto
    # the baseline instead would label valid new geometry as protected whenever
    # its nearest baseline point belongs to an unchanged face.
    protected_candidate = queries['baseline'].nearest(candidate_reference_hit)[0] <= scope_epsilon
    raw = {}
    if changed_candidate.any():
        a = candidate_reference_distance[changed_candidate]
        bdist = queries['candidate'].nearest(r[changed_ref])[0]
        raw['target_surface'] = surface_raw(a, bdist, request['target_half_scale_m'], evidence)
    else:
        raw['target_surface'] = {'status': 'absent', 'evidence': evidence,
            'reason': 'Candidate has no geometric change from the public baseline'}
    if protected_candidate.any():
        a = candidate_baseline_distance[protected_candidate]
        bdist = queries['candidate'].nearest(b[protected_base])[0]
        raw['protected_native'] = surface_raw(a, bdist, tolerance, evidence)
    else:
        raw['protected_native'] = {'status': 'absent', 'evidence': evidence,
            'reason': 'Candidate has no retained protected surface'}
    for atom in raw.values():
        atom.update(sample_count=count, random_seed=seed, scope_epsilon_m=scope_epsilon,
            reference_changed_samples=int(changed_ref.sum()), candidate_changed_samples=int(changed_candidate.sum()),
            baseline_protected_samples=int(protected_base.sum()), candidate_protected_samples=int(protected_candidate.sum()),
            scope='reference_baseline_surface_difference_and_reference_projection_v2')
    return raw


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    path = Path(sys.argv[sys.argv.index('--')+1]); request = json.loads(path.read_text())
    output = Path(request['output']); output.mkdir(parents=True, exist_ok=True)
    result = inspect(request, output) if request['operation'] == 'inspect' else compare(request, output)
    document = {'request_sha256': digest(path), 'worker_sha256': digest(__file__),
        'surface_kernel_sha256': digest(Path(__file__).with_name('continuous_surface.py')), 'result': result}
    (output / 'result.json').write_text(json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)+'\n')


if __name__ == '__main__': main()
