"""Explicit public numbers, separate from similarity to private reference assets."""
import math
import numpy as np


def compare_number(actual, definition):
    """Exact integer counts; tolerance applies only to continuous quantities."""
    expected, tolerance = definition['expected'], definition.get('tolerance', 0.)
    if not isinstance(actual, (int, float)) or not math.isfinite(actual):
        return {'status': 'not_measurable', 'actual': None, 'passed': False, 'score': 0.}
    error = abs(actual - expected)
    passed = error <= tolerance and (definition['unit'] != 'count' or float(actual).is_integer())
    return {'status': 'measured', 'actual': actual, 'absolute_error': error,
            'passed': bool(passed), 'score': float(passed)}


def measure_numbers(evidence, definitions):
    rows = []
    for definition in definitions:
        method = definition['method']
        if method == 'camera_local_translation':
            cameras = evidence.get('scene', {}).get('cameras', {})
            a, b = cameras.get('__main'), cameras.get('__alternate')
            if not a or not b:
                result = compare_number(None, definition)
            else:
                scale = evidence['scene'].get('unit_scale', 1.)
                delta = (np.asarray(b['location']) - a['location']) * scale
                direction = np.asarray(a['basis_x'])
                length = float(np.linalg.norm(direction))
                if not math.isfinite(length) or length <= 1e-12:
                    raise ValueError('Nondegenerate main camera basis required')
                direction = direction / length
                error = float(np.linalg.norm(delta - direction * definition['expected']))
                actual = float(delta @ direction)
                result = compare_number(actual, definition)
                # Equal separation in a wrong direction is not the specified translation.
                result.update(vector_error_m=error, passed=error <= definition['tolerance'],
                              score=float(error <= definition['tolerance']), displacement_m=delta.tolist())
        elif method == 'cylindrical_container_count':
            item = evidence.get('edit_components', {})
            actual = item.get('count_in_target_area') if item.get('status') == 'measured' else None
            result = compare_number(actual, definition)
        elif method == 'pending_geometry_count':
            result = {'status': 'pending_implementation', 'actual': None, 'passed': None, 'score': None,
                      'reason': 'Regional shape coverage does not prove an exact semantic part count'}
        else:
            raise ValueError('Unsupported public numerical method: ' + method)
        rows.append({**definition, **result})
    supported = [r for r in rows if r['status'] != 'pending_implementation']
    return {'status': 'partial' if len(supported) != len(rows) else 'measured',
            'score': float(np.mean([r['score'] for r in supported])) if supported else 0.,
            'requirements': rows, 'supported': len(supported), 'total': len(rows),
            'all_requirements_met': all(r['passed'] is True for r in rows),
            'scope': 'Published values only; unsupported counts are disclosed, never treated as satisfied'}


def validate_numbers(plan, public):
    rows = plan.get('numeric_requirements')
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Explicit unique public numerical requirements needed')
    for row in rows:
        if not row.get('source_quote') or row['source_quote'] not in public:
            raise ValueError('Numerical target must bind a public instruction quote')
        if (type(row['expected']) not in (int,float) or not math.isfinite(row['expected'])
                or row.get('tolerance', 0.) < 0 or row['unit'] not in {'m','count'}):
            raise ValueError('Invalid numerical target or tolerance')
        if row['unit'] == 'count' and (type(row['expected']) is not int or row.get('tolerance',0.) != 0):
            raise ValueError('Discrete public counts require exact integers')
