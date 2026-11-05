"""Shared bounded Astra invocation for the legacy-v2 effort adapters."""
from dataclasses import replace

from .responses_runtime import JUDGE_INSTRUCTIONS


SINGLE_ROUND_GUIDANCE = (
    'All required native inspection and diagnostic renders are prepared by trusted '
    'local tools before this request and attached with registered evidence paths. '
    'Evaluate the complete frozen checklist in one response. No tool interaction '
    'is available. Use authored images for composition and lighting, diagnostic '
    'views for geometry; names and bounding boxes do not prove component form. '
    'Return the complete required schema with concise observations. Mark checks '
    'unobservable when supplied evidence cannot establish them; do not invent facts.'
)

CONCISE_GUIDANCE = (
    ' Keep each achieved/discrepancies/reason/observation field to one short factual '
    'clause (normally at most 25 Chinese characters). Avoid repeating the question, '
    'evidence paths or the same observation in multiple text fields. Retain every '
    'required evidence entry and every judgment.'
)


def single_round_judge(config, *, visual=False, preview=True, preload_render_roles=None):
    """One model request after deterministic local native evidence collection."""
    config = compact_judge(config, visual=visual, preview=preview)
    if preload_render_roles is None:
        preload_render_roles = not visual
    return replace(config, responses_options={**config.responses_options,
        'max_rounds': 1, 'preload_scenes': not visual,
        'preload_render_roles': preload_render_roles}, inspection_guidance=SINGLE_ROUND_GUIDANCE)


def bounded_judge(config, *, visual=False, preview=True, max_rounds=2,
                  preload_render_roles=None):
    """A short fallback when one response cannot preserve the interactive score."""
    if type(max_rounds) is not int or not 1 <= max_rounds <= 4:
        raise ValueError('max_rounds must be between 1 and 4')
    result = single_round_judge(config, visual=visual, preview=preview,
                               preload_render_roles=preload_render_roles)
    return replace(result, responses_options={**result.responses_options,
                                               'max_rounds': max_rounds},
                   inspection_guidance=(SINGLE_ROUND_GUIDANCE if max_rounds == 1 else
                       'Inspect the supplied authored images, preloaded scene catalogues and '
                       'diagnostic views. Use the available read-only tools only for unresolved '
                       'requirements or unmet native evidence obligations; batch independent '
                       'requests. Reserve the final round for the complete frozen checklist JSON '
                       'with concise observations. Do not infer geometry from names or boxes.'))


def detail_single_round_judge(config):
    """Versioned detail invocation; retains all images and local native renders."""
    result=single_round_judge(config,preview=False)
    return replace(result,responses_options={**result.responses_options,'preload_scenes':False},
                   inspection_guidance=result.inspection_guidance+CONCISE_GUIDANCE)


def compact_judge(config, *, visual=False, preview=False):
    """Keep each rubric intact; remove CLI overhead and nested retry loops."""
    return replace(
        config, model='gpt-6-astra', effort='medium', attempts=1,
        engine='responses', image_transport='preview_webp' if preview else 'lossless_webp',
        responses_options={
            'max_rounds': 1 if visual else 4,
            'request_attempts': 1, 'max_output_tokens': 8000,
            'compact_tool_facts': True, 'preload_scenes': False,
            'system_instructions': JUDGE_INSTRUCTIONS,
        },
        inspection_guidance=(
            'Use the frozen checklist and read-only evidence. Batch independent '
            'inspection requests. Render only views needed to resolve requirements '
            'and meet native evidence obligations. Return the complete required '
            'schema with concise evidence. Reserve the final round for JSON.'),
    )


def configured_judge(config, campaign, *, visual=False, default='legacy'):
    """Activate a versioned call policy explicitly; never change it mid-run."""
    profile = campaign.get('judge_invocation_profile', default)
    if profile == 'legacy':
        return config
    if profile == 'single-round-v1':
        return single_round_judge(config, visual=visual)
    if profile not in {'compact-v1', 'compact-preview-v1'}:
        raise ValueError('Unknown judge invocation profile: ' + str(profile))
    return compact_judge(config, visual=visual, preview=profile == 'compact-preview-v1')


def sampled_variants(population, *, category=None, primary_only=False):
    """Select primary plus the first published seed; keep SingleView complete.

    Preserve native/export pairs. Published seed IDs need not start at zero.
    Selection never depends on observed scores or the tested model.
    """
    population = list(population)
    if not population or len(population) != len(set(population)):
        raise ValueError('A distinct published variant population is required')
    if category == 'Image2Code-SingleView' and not primary_only:
        return population
    seeds = list(dict.fromkeys(v.split('/')[0] for v in population))
    if 'primary' not in seeds:
        raise ValueError('Published primary variant required')
    selected = {'primary'}
    if not primary_only:
        alternatives = [s for s in seeds if s.startswith('seed-')]
        if not alternatives:
            raise ValueError('At least one published seed required')
        selected.add(alternatives[0])
    return [v for v in population if v.split('/')[0] in selected]
