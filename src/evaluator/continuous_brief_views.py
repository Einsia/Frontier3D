"""Continuous public camera relationships and same-scene image measurements.

Coordinates remain in the saved world frame. Intersecting optical axes measures
the cameras' common aim; it never transforms candidate or reference geometry.
"""
import math
import numpy as np
from .continuous_scene_preservation import CAMERA_FIELDS, deviation, semantic


def absent(reason, **observations):
    return {'status': 'absent', 'reason': reason, **observations}


def quantity(errors, **observations):
    values = [float(x) for x in errors]
    if not values or any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError('Finite nonnegative normalized errors required')
    return {'status': 'measured', 'normalized_errors': values, **observations}


def camera(scene, name):
    selected = [o for o in scene['objects'] if o['object'] == name and o['type'] == 'CAMERA']
    if len(selected) > 1: raise ValueError('Ambiguous saved camera')
    if not selected: return None
    obj = selected[0]; matrix = np.asarray(obj['matrix_world'], float)
    unit = float(scene['unit_scale'])
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all() or not math.isfinite(unit) or unit <= 0:
        raise ValueError('Invalid camera world transform or unit scale')
    norms = np.linalg.norm(matrix[:3, :3], axis=0)
    if np.any(norms <= 1e-12): raise ValueError('Degenerate saved camera basis')
    axes = matrix[:3, :3]/norms
    if np.max(np.abs(axes.T@axes-np.eye(3))) > 1e-5:
        raise ValueError('Sheared camera projection requires a dedicated measurement')
    return {'location': matrix[:3, 3]*unit, 'axes': axes, 'object': obj}


def pair(first, second, params):
    if first is None or second is None: return absent('A required saved camera is absent')
    a, b = first['location'], second['location']; delta = b-a
    az, bz = first['axes'][:, 2], second['axes'][:, 2]
    mode = params['mode']
    if mode == 'distance':
        actual = float(np.linalg.norm(delta)); expected = float(params['delta_m'])
        tolerance = float(params['tolerance']); half_scale = .01*abs(expected)
        return quantity([max(abs(actual-expected)-tolerance, 0.)/half_scale],
                        distance_m=actual, expected_m=expected, tolerance_m=tolerance, half_scale_m=half_scale)
    denominator = np.linalg.norm(az[:2])*np.linalg.norm(bz[:2])
    if denominator <= 1e-12: return absent('A vertical optical axis has no required azimuth')
    angle = math.degrees(math.acos(float(np.clip(np.dot(az[:2], bz[:2])/denominator, -1, 1))))
    if mode == 'different_azimuth':
        # Public task 010 requires a distinct direction without a target angle.
        # Smooth positive separation credit; 1 degree is the frozen half scale.
        score = -math.expm1(-math.log(2)*max(angle-1e-4, 0.))
        if score <= 0: return absent('The two camera azimuths coincide', azimuth_degrees=angle)
        return quantity([-math.log2(score)], azimuth_degrees=angle, separation_half_scale_degrees=1.)
    if mode != 'orbit': raise ValueError('Unsupported public camera relationship: '+mode)
    distances, _, rank, _ = np.linalg.lstsq(np.column_stack((az, -bz)), delta, rcond=None)
    if rank < 2 or not np.all(distances < 0):
        return absent('Optical rays have no common forward aim', azimuth_degrees=angle,
                      signed_axis_distances_m=distances.tolist())
    focus_a, focus_b = a+distances[0]*az, b+distances[1]*bz
    separation = float(np.linalg.norm(focus_a-focus_b))
    radius_error = abs(float(distances[0]-distances[1]))
    radius = abs(float(distances[0])); length_tolerance = .01*radius
    angle_tolerance = float(params.get('tolerance', .25))
    if radius <= 1e-9: return absent('Camera has no positive orbit radius')
    optical = lambda c: {'projection': {k: c['object']['settings'].get(k) for k in CAMERA_FIELDS},
                         'dof': semantic(c['object'].get('dof'))}
    projection = deviation(optical(first), optical(second))
    if projection['score'] <= 0:
        return absent('Required camera projection is not preserved', projection=projection)
    errors = {'azimuth': max(abs(angle-params['degrees'])-angle_tolerance, 0.)/angle_tolerance,
              'height': max(abs(float(delta[2]))-length_tolerance, 0.)/length_tolerance,
              'common_aim': max(separation-length_tolerance, 0.)/length_tolerance,
              'distance': max(radius_error-length_tolerance, 0.)/length_tolerance,
              'projection': -math.log2(projection['score'])}
    return quantity([max(errors.values())], azimuth_degrees=angle,
                    focus_ray_separation_m=separation, view_distance_error_m=radius_error,
                    height_difference_m=float(delta[2]), inferred_focus_m=((focus_a+focus_b)/2).tolist(),
                    reference_view_distance_m=radius, length_tolerance_and_half_scale_m=length_tolerance,
                    angle_tolerance_and_half_scale_degrees=angle_tolerance,
                    projection=projection, normalized_suberrors=errors,
                    aggregation='worst required relationship; no independent field dilution')


def configuration(selected, params):
    if selected is None: return absent('The prescribed camera is absent')
    obj = selected['object']; errors = []; observations = {}
    if 'projection' in params:
        observations['projection'] = obj['settings']['type']
        if observations['projection'] != params['projection']:
            return absent('Required categorical projection is absent', **observations)
        errors.append(0.)
    if 'elevation' in params:
        z = selected['axes'][:, 2]
        angle = math.degrees(math.atan2(float(z[2]), float(np.linalg.norm(z[:2]))))
        lower, upper = params['elevation']; half_scale = .01*max(abs(lower), abs(upper))
        errors.append(max(lower-angle, angle-upper, 0.)/half_scale)
        observations.update(elevation_degrees=angle, elevation_range_degrees=[lower, upper], half_scale_degrees=half_scale)
    if set(params)-{'camera', 'projection', 'elevation'}: raise ValueError('Unimplemented camera configuration field')
    return quantity([max(errors)], **observations)


def image_error(candidate, rerender, half_scale):
    a, b = np.asarray(candidate), np.asarray(rerender)
    if a.shape != b.shape: return absent('Submitted and rerendered image grids differ', candidate_shape=list(a.shape), rerender_shape=list(b.shape))
    if a.ndim != 3 or a.shape[2] != 4 or a.dtype != np.uint8 or b.dtype != np.uint8:
        raise ValueError('Unresized RGBA uint8 image arrays required')
    # Alpha is evidence too. A transparent fake cannot disappear in RGB means.
    error = float(np.abs(a.astype(float)-b.astype(float)).mean()/255.)
    return quantity([error/half_scale], normalized_pixel_mae=error, half_scale=half_scale,
                    channels='RGBA', resized=False, pixels=int(a.shape[0]*a.shape[1]))


def measure(scene, views, parameters, images, evidence):
    names = {key: views[key]['camera'] for key in ('main.png', 'alternate.png')}
    cameras = {key: camera(scene, name) for key, name in names.items()}
    quantities = []
    for key in names:
        quantities.append({'id': key, **image_error(*images[key], parameters['image_error_half_scale'])})
    for check in parameters['camera_checks']:
        p = check['params']
        if check['metric'] == 'l2_case_camera_pair':
            result = pair(cameras['main.png'], cameras['alternate.png'], p)
        elif check['metric'] == 'camera_config':
            key = {'__main': 'main.png', '__alternate': 'alternate.png'}[p['camera']]
            result = configuration(cameras[key], p)
        else: raise ValueError('Unimplemented public camera check')
        quantities.append({'id': check['id'], **result})
    return {'status': 'measured', 'quantities': quantities, 'evidence': evidence,
            'cameras': names, 'parameters': parameters, 'registration': 'none',
            'scope': 'Full submitted/rerendered pixel arrays and public saved-camera relationships',
            'limitations': 'Common aim is inferred from optical rays; semantic framing is judged separately.'}
