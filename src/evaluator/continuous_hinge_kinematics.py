"""Measure annotated cabinet mechanisms in unchanged world coordinates.

Annotations identify observed parts, never desired scores or reference poses.
Point correspondences stay on the same extracted vertices throughout the cycle.
"""
import numpy as np
from .continuous_assembly_state import weights, anchors
from .continuous_hinge_motion import error_row, rigidity, hinge_invariants, coaxial_slide


def value(raw):
    if raw['status'] == 'absent': return 0.
    if raw['status'] != 'measured': raise ValueError(raw.get('reason', 'Kinematic measurement unavailable'))
    return float(np.exp2(-np.asarray(raw['normalized_errors'], float)).mean())


def combined(meshes):
    vertices, faces, count = [], [], 0
    for v, f in meshes:
        vertices.append(v); faces.append(f+count); count += len(v)
    if not vertices: raise ValueError('Annotated geometry role is empty')
    return np.concatenate(vertices), np.concatenate(faces)


def sequence(states, names):
    meshes = [combined([state[name] for name in names]) for state in states]
    v, f = meshes[0]
    if any(w.shape != v.shape or not np.array_equal(t, f) for w, t in meshes[1:]):
        raise ValueError('Annotated motion vertex correspondence changed')
    return meshes


def centre(mesh):
    v, f = mesh; w, _ = weights(v, f)
    return w@v


def observed_axis(meshes, main_mesh):
    """Track the same two cap-ring populations selected from the closed geometry."""
    points = np.unique(main_mesh[0], axis=0); cov = np.cov(points.T)
    _, basis = np.linalg.eigh(cov); direction = basis[:, -1]
    if direction[2] < 0: direction = -direction
    vertices = meshes[0][0]; coordinate = vertices@direction
    span = float(np.ptp(coordinate))
    if span <= 1e-7: raise ValueError('Observed strut axis has no extent')
    low = np.flatnonzero(coordinate <= coordinate.min()+1e-7)
    high = np.flatnonzero(coordinate >= coordinate.max()-1e-7)
    trajectory = np.array([[v[low].mean(0), v[high].mean(0)] for v, _ in meshes])
    return trajectory, {'initial_direction': direction.tolist(), 'lower_vertex_indices': low.tolist(),
        'upper_vertex_indices': high.tolist(), 'endpoint_rule': 'centres of fixed closed-state extreme vertex rings'}


def closest_point(point, mesh):
    """Exact point-to-triangle distance in float64, including triangle interiors."""
    vertices, faces = np.asarray(mesh[0],dtype=float), np.asarray(mesh[1],dtype=int)
    xyz = vertices[faces]; a, b, c = xyz[:,0], xyz[:,1], xyz[:,2]
    ab, ac = b-a, c-a; normal = np.cross(ab, ac); n2 = np.einsum('ij,ij->i',normal,normal)
    usable = n2 > 0
    projected = a.copy(); projected[usable] = point-normal[usable]*(np.einsum('ij,ij->i',point-a[usable],normal[usable])/n2[usable])[:,None]
    delta = projected-a; aa = np.einsum('ij,ij->i',ab,ab); cc = np.einsum('ij,ij->i',ac,ac)
    abac = np.einsum('ij,ij->i',ab,ac); d = aa*cc-abac*abac
    u = np.zeros(len(faces)); v = u.copy(); good = usable & (d > 0)
    da = np.einsum('ij,ij->i',delta,ab); dc = np.einsum('ij,ij->i',delta,ac)
    u[good] = (cc[good]*da[good]-abac[good]*dc[good])/d[good]
    v[good] = (aa[good]*dc[good]-abac[good]*da[good])/d[good]
    inside = good & (u >= 0) & (v >= 0) & (u+v <= 1)
    candidates = [projected[inside]]
    for first, second in ((a,b),(b,c),(c,a)):
        edge = second-first; length = np.einsum('ij,ij->i',edge,edge)
        t = np.divide(np.einsum('ij,ij->i',point-first,edge), length, out=np.zeros_like(length), where=length>0)
        candidates.append(first+np.clip(t,0,1)[:,None]*edge)
    points = np.concatenate(candidates); distances = np.linalg.norm(points-point,axis=1)
    i = int(distances.argmin()); return points[i], float(distances[i])


def fixed_landmark(meshes, point):
    """Bind a point to four real vertices; no scene transform is estimated/applied."""
    v, f = meshes[0]; w, _ = weights(v,f); ids = np.asarray(anchors(v,w),dtype=int)
    basis = (v[ids[1:]]-v[ids[0]]).T
    if abs(float(np.linalg.det(basis))) <= 1e-18: raise ValueError('Receiver lacks a stable volume landmark basis')
    coordinates = np.linalg.solve(basis, point-v[ids[0]])
    coefficients = np.r_[1-coordinates.sum(),coordinates]
    return np.array([coefficients@vertices[ids] for vertices,_ in meshes]), {
        'vertex_indices': ids.tolist(), 'barycentric_coefficients': coefficients.tolist(),
        'meaning': 'fixed material landmark on this observed receiver; no reference registration'}


def attachment(states, endpoints, receivers, *, spherical=False, half_scale=.01):
    candidates = []
    for name in receivers:
        meshes = sequence(states,[name]); mesh = meshes[0]
        if spherical:
            anchor = centre(mesh); radius = float(np.linalg.norm(mesh[0]-anchor,axis=1).max())
            gap = max(float(np.linalg.norm(endpoints[0]-anchor))-radius,0.)
        else:
            anchor, gap = closest_point(endpoints[0],mesh); radius = 0.
        candidates.append((gap,name,anchor,radius,meshes))
    if not candidates: raise ValueError('Attachment receiver annotations required')
    _, name, anchor, radius, meshes = min(candidates,key=lambda x:(x[0],x[1]))
    trajectory, landmark = fixed_landmark(meshes,anchor)
    distances = np.maximum(np.linalg.norm(endpoints-trajectory,axis=1)-radius,0)
    return error_row([float(distances.max())],half_scale, receiver=name, receiver_radius_m=radius,
        receiver_type='observed_ball_joint' if spherical else 'fixed_receiver_surface_point',
        receiver_landmark=landmark, endpoint_trajectory_m=endpoints.tolist(),
        receiver_trajectory_m=trajectory.tolist(), per_frame_gap_m=distances.tolist(),
        temporal_aggregation='maximum gap to the same receiver selected at the closed frame')


def grouped(name, score, observations):
    if not np.isfinite(score) or not 0 <= score <= 1: raise ValueError('Invalid kinematic score')
    return {'id':name, 'status':'measured' if score > 0 else 'absent',
        'normalized_errors':[-float(np.log2(score))] if score > 0 else [],
        'reason':None if score > 0 else 'Required geometric motion or connection absent', 'observations':observations}


def measure(states, frames, roles, *, point_half_scale=.01, rigid_half_scale=.005):
    expected = list(range(1,122,10))+[1]
    if list(frames) != expected or len(states) != len(frames): raise ValueError('Complete fixed cycle and restoration required')
    if (len(roles['hinges']) != 2 or len(set(roles['hinges'])) != 2 or len(roles['struts']) != 2
            or len({s['id'] for s in roles['struts']}) != 2):
        raise ValueError('Two distinct hinges and two distinct support annotations required')
    if not np.isfinite([point_half_scale,rigid_half_scale]).all() or min(point_half_scale,rigid_half_scale)<=0:
        raise ValueError('Positive finite public measurement scales required')
    groups=[roles['door']]+[side[key] for side in roles['struts'] for key in ('barrel','rod')]
    identities=[name for group in groups for name in group]
    if any(not group for group in groups) or len(set(identities))!=len(identities):
        raise ValueError('Five nonempty disjoint rigid assemblies required')
    for side in roles['struts']:
        if side['barrel_main'] not in side['barrel'] or side['rod_main'] not in side['rod']:
            raise ValueError('Observed main strut geometry must belong to its assembly')
    door = sequence(states,roles['door']); axis = np.array([centre(sequence(states,[name])[0]) for name in roles['hinges']])
    direction = axis[1]-axis[0]; length = np.linalg.norm(direction)
    if length<=1e-7: raise ValueError('Distinct observed hinge centres required')
    direction /= length
    vertices, triangles = door[0]; w, _ = weights(vertices,triangles)
    radial = vertices-axis[0]; radial -= (radial@direction)[:,None]*direction
    keep = (np.linalg.norm(radial,axis=1)>1e-7) & (w>0)
    if not keep.any(): raise ValueError('Door surface lacks radial witnesses')
    witnesses = np.array([v[keep] for v,_ in door])
    hinge = hinge_invariants(witnesses,axis,half_scale_m=point_half_scale)
    hinge_score = float(np.sum(w[keep]*np.exp2(-np.asarray(hinge['normalized_errors'])))/w[keep].sum())
    centers = np.array([centre(mesh) for mesh in door]); z = centers[:,2]; indices = {f:frames.index(f) for f in (1,31,61,91,121)}
    movements = [z[indices[31]]-z[indices[1]],z[indices[61]]-z[indices[31]],
                 z[indices[91]]-z[indices[121]],z[indices[61]]-z[indices[91]]]
    excursion = max(min(movements)-1e-7,0.)
    activity = float(-np.expm1(-np.log(2)*excursion/point_half_scale))
    closed = max(float(np.linalg.norm(door[i][0]-vertices,axis=1).max()) for i in (indices[121],len(frames)-1))
    reversal = max(float(np.maximum(-np.diff(z[:indices[61]+1]),0).max()),
                   float(np.maximum(np.diff(z[indices[61]:indices[121]+1]),0).max()))
    stable_hinges = max(float(np.linalg.norm(centre(state_mesh)-axis[i])) for i,name in enumerate(roles['hinges'])
                        for state_mesh in sequence(states,[name]))
    cycle = error_row([max(closed,reversal,stable_hinges)],point_half_scale)
    door_score = min(hinge_score,activity,value(cycle))
    quantities = [grouped('door_hinge_motion',door_score,{'hinge_invariants':hinge,
        'hinge_area_weighted_score':hinge_score,'door_centroids_m':centers.tolist(),'upward_phase_displacements_m':movements,
        'upward_activity_score':activity,'cycle':cycle,'closed_return_error_m':closed,
        'monotonicity_violation_m':reversal,'hinge_axis_drift_m':stable_hinges})]
    attachments, slides = [], []; rigid = [rigidity(door,frames,half_scale_m=rigid_half_scale)]
    for side in roles['struts']:
        barrel = sequence(states,side['barrel']); rod = sequence(states,side['rod'])
        outer, outer_binding = observed_axis(barrel,states[0][side['barrel_main']])
        inner, inner_binding = observed_axis(rod,states[0][side['rod_main']])
        attachments.extend([
            attachment(states,outer[:,0],side['cabinet_receivers'],spherical=side['cabinet_ball'],half_scale=point_half_scale),
            attachment(states,inner[:,1],side['door_receivers'],spherical=side['door_ball'],half_scale=point_half_scale)])
        # Coaxial slide uses the main barrel/rod, excluding wider joint sockets.
        oa, _ = observed_axis(sequence(states,[side['barrel_main']]),states[0][side['barrel_main']])
        ia, _ = observed_axis(sequence(states,[side['rod_main']]),states[0][side['rod_main']])
        telescoping = coaxial_slide(oa,ia,half_scale_m=point_half_scale)
        excursion = max(telescoping['sliding']['excursion_m']-1e-7,0.)
        slide = float(-np.expm1(-np.log(2)*excursion/point_half_scale))
        q = min(value(telescoping['alignment']),value(telescoping['nesting']),slide)
        slides.append({'side':side['id'],'score':q,'raw':telescoping,'precision_corrected_sliding_score':slide,
                       'barrel_endpoint_binding':outer_binding,'rod_endpoint_binding':inner_binding})
        rigid.extend([rigidity(barrel,frames,half_scale_m=rigid_half_scale),rigidity(rod,frames,half_scale_m=rigid_half_scale)])
    quantities.extend([
        grouped('four_support_attachments',sum(value(x) for x in attachments)/4,attachments),
        grouped('two_telescoping_struts',sum(x['score'] for x in slides)/2,slides),
        grouped('five_rigid_assemblies',sum(value(x) for x in rigid)/5,rigid)])
    return {'status':'measured','quantities':quantities,'frames':list(frames),
        'point_error_half_scale_m':point_half_scale,'rigid_shape_half_scale_m':rigid_half_scale,
        'group_aggregation':'four equally weighted required functional groups; fixed part populations',
        'registration':'none','physics_simulation':False}
