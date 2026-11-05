"""Task-specific pilot rubric. Weights are within an axis, never a total score."""
VERSION='l3-mc-anchored-v4-open-world-brief'
ANCHORS={0:'Absent, wrong or not demonstrated despite valid adequate evidence.',
 1:'Only weak recognizable intent; major omissions or pervasive defects.',
 2:'Partly achieved; substantial visible discrepancies in important properties.',
 3:'Most important properties achieved; only limited, concrete discrepancies remain.',
 4:'All important visible properties positively demonstrated, coherent and polished; no material discrepancy.'}
CAPS={'none':4,'minor':3,'major':2,'wrong_or_absent':0,'not_demonstrated':0}
CHECKS={
 'beauty_composition':('beauty','Evaluate hierarchy/readability of the village, districts, paths and focal elements across overview, street and interior views. Quantity and a recognizable village alone earn no polish credit.'),
 'beauty_lighting':('beauty','Evaluate exposure, readable light/shadow, color relationships and separation of surfaces in all supplied views. Washed-out surfaces, lost contrast or pervasive flat light are material defects even when scene content is rich.'),
 'beauty_finish':('beauty','Evaluate authored material/shape finish at inhabited scale: surfaces, edges, joins, furniture and props. Deliberate Minecraft simplicity is allowed; unfinished generic placeholders, indistinguishable surfaces and inconsistent finish are not automatically stylistic choices.'),
 'beauty_detail':('beauty','Evaluate meaningful distribution and variation of detail across districts and interiors: large/medium/small scale balance, coherent environmental storytelling and avoidance of visually monotonous repetition. Count alone is insufficient; do not require photorealistic complexity.'),
 'prompt_village':('prompt_alignment','Check the public brief for a substantial irregular plains village, branching street network, varied houses and connected terrain. Judge explicitly requested semantic organization; do not prescribe private world coordinates or require screenshot pixel equality.'),
 'prompt_districts':('prompt_alignment','Check the public brief for two distinct smithies, storehouse, farms and pen. Require recognizable, meaningful differences between these functions; labels, IDs and repeated generic sheds do not establish function.'),
 'prompt_interiors':('prompt_alignment','Check furnished, usable-looking interiors and requested role-specific furnishings across the sampled buildings. A repeated single furniture layout cannot demonstrate all different roles. Do not infer hidden missing rooms from a bad camera; that is a technical evidence limitation.'),
 'prompt_landscape':('prompt_alignment','Check the reference-grounded terrain, vegetation, distant scenery and village context across the full environment requested in the public brief. Do not infer interaction success or invisible inventory from these images. Visible thematic content only; exact geometry belongs to deterministic measurements.'),
 'style_shapes':('style_consistency','Compare the requested Minecraft block-built shape vocabulary across buildings, roofs, terrain steps, tree trunks/canopies, furniture and props. Check consistent grid/shape scale and readable characteristic silhouettes. A few cubes or a generic voxel scene are insufficient for excellent consistency.'),
 'style_materials':('style_consistency','Compare Minecraft material/texture language and scale across grass/earth, wood, stone, vegetation and props against the public reference. Evaluate coherent surface patterns and distinguishability; exact pixel colors and lighting fidelity belong to reference accuracy, not this axis.'),
 'style_cross_views':('style_consistency','Check that all supplied districts and interiors share the requested visual language, proportions and level of abstraction. Identify localized style breaks or generic substitutes. Consistency is not equivalent to making all buildings/interiors identical.'),
}

def validate_verdict(v):
    if v['not_judgeable']:
        if v['score'] is not None:raise ValueError('Technical non-judgeability needs null score')
        return
    if v['score'] is None or v['score']>CAPS[v['discrepancy_severity']]:
        raise ValueError('Grade contradicts its declared discrepancy severity')
    if not v['achieved'].strip() or not v['discrepancies'].strip():
        raise ValueError('Both positive and discrepancy evidence required')
