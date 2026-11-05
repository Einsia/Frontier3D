"""Separate partial RNG observations from bounded artifact reproducibility."""

from __future__ import annotations


def observation_scope(trace, *, trace_status):
    """Describe the current runner wrappers; never infer absence of randomness.

    Candidate-side trace transport is not adversarially authenticated. A valid
    trace/seed binding says where an observation came from, not that all random
    sources have been observed or that the candidate actually used that seed.
    """
    counters = trace.get('module_calls') if isinstance(trace, dict) else None
    valid = (trace_status == 'observed' and isinstance(counters, dict)
             and all(isinstance(k, str) and type(v) is int and v >= 0 for k, v in counters.items()))
    groups = {
        'python_module_wrappers': lambda name: '.' not in name,
        'python_random_instances': lambda name: name.startswith('python.Random.'),
        'numpy_public_module_wrappers': lambda name: name.startswith('numpy.random.'),
        'numpy_public_instance_wrappers': lambda name: name.startswith(('numpy.Generator.', 'numpy.RandomState.')),
    }
    families = {name: {'status': 'partial' if valid else 'not_configured',
                       'observed_calls': sum(n for key, n in counters.items() if select(key)) if valid else None,
                       'scope': 'wrapped_interfaces_only_not_all_family_calls'}
                for name, select in groups.items()}
    for name in ('numpy_extension_aliases', 'numpy_raw_bitgenerator_and_c_api',
                 'blender_mathutils_noise', 'blender_cpp_and_plugins', 'system_entropy_and_other_libraries'):
        families[name] = {'status': 'not_configured', 'observed_calls': None,
                          'reason': 'No complete interception or internal-state observation in the current runner'}
    return {'protocol': 'l1-rng-observability-v1', 'status': 'partial' if valid else 'not_configured',
            'families': families, 'all_random_sources_observed': False, 'determinism_proven': False,
            'trace_authenticity': 'candidate_process_stdout_not_adversarially_trusted',
            'limitation': 'Zero wrapped calls is not evidence of no RNG use; state digests cover only exposed states'}


def summarize_rng_evidence(record):
    """Reference existing semantic comparisons, without re-scoring or RNG claims."""
    semantics = record['reproduction_consistency']
    expected = semantics['expected_seeds']
    baseline = record['reconstruction_baseline']
    baseline_binding = baseline['execution_binding']
    baseline_intact = record['baseline_integrity_passed']
    rows = {}
    for seed in expected:
        run = record['seed_runs'].get(str(seed), {})
        measured = semantics['per_seed'].get(str(seed), {})
        binding = run.get('execution_binding', {})
        same_execution = bool(binding) and measured.get('execution_binding') == binding
        same_execution = same_execution and all(binding.get(key) == value for key, value in {
            'task_id': record['task_id'], 'trial_id': record['trial_id'], 'repair_round': record['repair_round'],
            'program_seed': seed, 'source_snapshot_digest': record['source_snapshot']['digest'],
        }.items())
        bound = bool(baseline_intact and same_execution and run.get('resource_integrity_passed')
                     and measured.get('baseline_binding', {}).get('execution_binding') == baseline_binding
                     and measured.get('resource_binding') == run.get('resource_binding')
                     and measured.get('execution_attempted') is True)
        status = measured.get('status') if bound and measured.get('status') in {'ok', 'failed'} else 'not_measurable'
        rows[str(seed)] = {
            'execution_binding': binding,
            'observation': binding.get('rng_observation_scope', observation_scope(None, trace_status='not_configured')),
            'artifact_evidence': {'status': status, 'source': f'reproduction_consistency.per_seed.{seed}',
                                  'binding_verified': bound,
                                  'reason': None if status in {'ok', 'failed'} else 'No intact, executed, bound semantic comparison'},
        }
    statuses = [row['artifact_evidence']['status'] for row in rows.values()]
    status = 'not_measurable' if not statuses or 'not_measurable' in statuses else 'ok' if all(s == 'ok' for s in statuses) else 'failed'
    return {'protocol': 'l1-rng-evidence-v1', 'hard_gate': False,
            'baseline_observation': baseline_binding.get('rng_observation_scope', observation_scope(None, trace_status='not_configured')),
            'per_seed': rows, 'alternative_consistency': {'status': status, 'denominator': len(expected),
                'measured_count': sum(s in {'ok', 'failed'} for s in statuses), 'passed_count': statuses.count('ok'),
                'global_resource_integrity_passed': record['resource_integrity_passed'],
                'scope': 'existing_artifact_comparisons_for_declared_seeds_and_supported_geometry_materials'},
            'all_random_sources_observed': False, 'determinism_proven': False,
            'limitations': ['No general deterministic-program or correct-task claim',
                            'Unsupported material/geometry and hidden RNG paths retain their own limitations',
                            'No candidate stdout authentication or new security guarantee']}
