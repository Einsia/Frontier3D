"""Frozen suite measurement policy and public task resolution."""
from pathlib import Path
import json,os
from harness.L3.MinecraftVillage.algorithm_scores import POLICY as MC_POLICY
from harness.L3.MinecraftVillage.rubric import ANCHORS
ROOT=Path(__file__).resolve().parents[3]
BATCH=ROOT/'data/l3/suite-20261023'
MODEL=os.environ.get('L3_EVAL_MODEL','gpt-6-astra')
if MODEL not in {'gpt-6-astra','gpt-6-luna','gpt-6-sol','claude-opus-5-5','glm-5.3-flash','kimi-k3','deepseek-v4.1-flash','qwen3.8-max','gpt-6.1-sol','MiniMax-M3.1-Flash','doubao-seed-evolving','kimi-k3.1-pro'}:raise ValueError('Unsupported evaluated model')
MODEL_SLUG=MODEL.removeprefix('gpt-6-')
OUT=Path(os.environ.get('L3_EVAL_OUT',str(ROOT/'data/l3/evaluations'/('suite-'+MODEL_SLUG+'-v1'))))
POLICY={**MC_POLICY,'version':'l3-suite-algorithm-v1','formal_score_eligible':True,
 'static_overlap_policy':'same-actor static assembly internal pairs omitted; required mechanisms and independent actors checked; public water entities excluded from rigid-volume tests',
 'local_weights':{'presence':.2,'positive_physical_effect':.5,'invalid_reach_rejected':.3},
 'motion_policy':{'penetration_cm':2.,'intersection_cm3':8.,'pose_sample_seconds':.2},
 'navigation_tolerance_cm':60.,'object_containment_tolerance_cm':15.,
 'reference_policy':'fixed reference population; semantic box localization; deterministic L2 box and appearance metrics with fixed semantic instance correspondence; submitted matched reference cameras',
 'open_surface_policy':'closed solids use SAT or exact intersection volume; open render meshes use proper noncoplanar triangle crossings at 2 cm tolerance; no invented closure volume',
 'workflow_policy':'independent execution of declared route, independent physical goal predicates; candidate state strings never establish success'}
CHECKS={
 'beauty_composition':('beauty','Spatial hierarchy, readable focal elements, balanced distribution across overview and interior views.'),
 'beauty_lighting':('beauty','Exposure, surface readability, light/shadow and color relationships across all views.'),
 'beauty_finish':('beauty','Coherent materials, well-resolved shapes, joins and props; placeholders are not automatically stylistic choices.'),
 'beauty_detail':('beauty','Meaningful detail and variation at large, medium and small scales appropriate to the requested setting.'),
 'prompt_extent':('prompt_alignment','Requested scene extent, connected zones and principal architectural or environmental features.'),
 'prompt_functions':('prompt_alignment','Visible differentiation of all requested functional areas and task-specific fittings; labels alone are insufficient.'),
 'prompt_interiors':('prompt_alignment','Furnished, usable-looking interiors or sheltered working spaces as required by the task.'),
 'prompt_context':('prompt_alignment','Requested surrounding context, landscape and environmental content; do not infer invisible interactions.'),
 'style_shapes':('style_consistency','Characteristic shapes, proportions and silhouettes consistent with the requested game or real environment.'),
 'style_materials':('style_consistency','Requested material vocabulary and texture scale, coherently applied to architecture and props.'),
 'style_cross_views':('style_consistency','Consistency of visual language and level of abstraction across all zones and views.'),
 'layout_semantics':('layout_semantics','Intelligible access, appropriate adjacencies, sensible placement and usable-looking working space; numerical collision/support are measured separately.')}
def task_paths():
 return {json.loads(p.read_text())['task_key']:p.parents[2] for p in (ROOT/'tasks/L3').glob('*/environment/input/interaction-contract.json')}
def read(p):return json.loads(Path(p).read_bytes())
def write(p,x):p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def submission_trial(key):
 override=os.environ.get('L3_EVAL_TRIAL')
 return Path(override).resolve() if override else BATCH/key/MODEL_SLUG
