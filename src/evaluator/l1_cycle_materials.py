"""Middle-state material observations separate from endpoint restoration."""

from __future__ import annotations

from .l1_field_comparison import compare_compiled_material_fields
from .l1_materials import compare_material_surfaces


def compare_middle_materials(left, middle, config, *, tolerance_m, material_tolerance):
    options = {'trusted_root': config.trusted_root, 'parameter_tolerance': material_tolerance,
               'surface_tolerance_m': tolerance_m, 'levels': config.surface_levels,
               'seed': config.seed, 'pose_alignment': True}
    constant = compare_material_surfaces(left, middle, scope='native_constant_principled',
                                         convergence_m=config.surface_convergence_m, **options)
    compiled = compare_compiled_material_fields(left, middle,
                                                registration_convergence_m=config.surface_convergence_m,
                                                **{**options, 'levels': (64, 256)})
    return {'protocol': 'l1-middle-materials-v1', 'hard_gate': False,
            'scope': 'first_to_middle_pose_anchored_material_input_observations',
            'constant_parameters': constant, 'compiled_fields': compiled,
            'complete_material_equivalence': None,
            'not_assessed': ['final_bsdf_equivalence', 'general_nodes_volumes_displacement',
                             'shading_normals_tangents', 'unresolved_internal_material_motion',
                             'task_role_colors_and_thresholds']}


def material_cycle_summary(parts):
    def aggregate(values):
        return 'failed' if 'failed' in values else 'not_measurable' if not values or any(s != 'ok' for s in values) else 'ok'
    rows = []
    for part in parts:
        middle = part.get('middle_materials', {})
        endpoint = part.get('materials', {})
        compiled = [item.get('compiled_field_diagnostic', {}).get('status', 'not_measurable')
                    for item in endpoint.get('matches', [])]
        rows.append({'session_identity': part['session_identity'],
                     'middle_constant': middle.get('constant_parameters', {}).get('status', 'not_measurable'),
                     'middle_compiled': middle.get('compiled_fields', {}).get('status', 'not_measurable'),
                     'return_constant': endpoint.get('status', 'not_measurable'),
                     'return_compiled': aggregate(compiled)})
    return {'protocol': 'l1-material-cycle-v1', 'hard_gate': False,
            'scope': 'middle_and_return_input_diagnostics_by_fixed_identity', 'parts': rows,
            'constant_parameter_status': aggregate([r[k] for r in rows for k in ('middle_constant', 'return_constant')]),
            'compiled_field_status': aggregate([r[k] for r in rows for k in ('middle_compiled', 'return_compiled')]),
            'complete_material_equivalence': None,
            'limitation': 'Raw parameter differences and compiled input differences are not a final BSDF verdict'}
