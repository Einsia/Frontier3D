# L1/L2 metric reference

[Scoring guide](../scoring.md) · [Documentation](../../README.md)

This reference describes component measurements. Final weights, detail variants and task-specific overrides are in [Scoring](../scoring.md). Use each task's contract and report `method_version` to identify the measurement actually used.

## Reference-image appearance

Candidate and reference images are compared on their original pixel grids. Candidate-fitted translation, scaling, cropping, homography or camera registration is not used to improve similarity. Incompatible image dimensions remain a comparability or delivery problem. Primary/alternate correspondences are frozen before evaluation; diagnostic views do not replace the scoring view. L2 refresh can average fixed primary/alternate pairs or compare only contract-defined static regions.

### Global appearance

[l2_reference_image.appearance_components](../../../src/evaluator/l2_reference_image.py) implements `native-appearance-v1`:

~~~text
I_global = 0.45 S_structure + 0.25 S_color + 0.15 S_tone + 0.15 S_edge
~~~

| Term | Calculation |
| --- | --- |
| Structure | Mean RGB SSIM at fixed Gaussian smoothing sigma 0, 2 and 6; clipped to `[0,1]` |
| Color | Mean Lab difference over a fixed 4×4 grid: `exp(-DeltaE/25)` |
| Tone | Mean L* difference on the same grid: `exp(-DeltaL/20)` |
| Edge | Symmetric mean Canny-edge distance divided by image diagonal: `exp(-d/0.02)` |

One-sided missing edges score zero; two empty edge sets score one for that edge term. Background and color similarity can leave residual appearance credit for poor content, so interpret appearance alongside localization, semantics and detail. Color/tone cannot uniquely separate material, lighting and exposure.

### Fixed reference regions

[l2_reference_regions.regional_components](../../../src/evaluator/l2_reference_regions.py) implements `reference-regions-v1`. All candidates use the same reference-owned polygons and weights:

~~~text
I_r = (0.50 SSIM_r + 0.30 EdgeF1_r + 0.20 Color_r)
      * sqrt(DetailRatio_r * ContrastRatio_r)
I_subject = sum(w_r * I_r)
I_region = 0.90 I_subject + 0.10 I_global
~~~

`SSIM_r` averages sigma 0/2/6 maps within a region. `EdgeF1_r` uses bidirectional edge precision/recall, with pixel tolerance `max(2, 0.01 * image_diagonal)`. `Color_r = exp(-DeltaE/25)`. Detail ratio is the smaller edge count divided by the larger; no reference edges gives zero. Contrast ratio uses the smaller/larger grayscale standard deviation; no effective variation on either side gives zero.

[l2_refresh_scoring.compare_views](../../../src/evaluator/l2_refresh_scoring.py) follows `appearance_views`; `static_regions_only` uses `I_subject` without the global term. These polygons are 2D regions, not semantic segmentation or hidden-surface ground truth.

[l1_image_pair.py](../../../src/evaluator/l1_image_pair.py) also provides `silhouette_iou * region_macro` for native intermediate measurements. It is distinct from the final reference-regions measurement. The four final visual overrides are listed in [Scoring](../scoring.md#task-specific-overrides).

## Localization

Reference classes, instance boxes, weights and boundary policies are frozen. The VLM observes candidate `main.png` and returns normalized XYXY boxes; the program validates, matches and aggregates them. Candidate object names, self-reported boxes and camera metadata do not replace image observations. A measured unrecognized class can return an empty list and score zero; an API failure remains missing.

[l2_reference_boxes.py](../../../src/evaluator/l2_reference_boxes.py) defines:

~~~text
d_center = pixel_distance(center_a, center_b) / image_diagonal
C = max(0, 1 - d_center/0.25)
Z = sqrt(min(w_a,w_b)/max(w_a,w_b) * min(h_a,h_b)/max(h_a,h_b))
P(a,b) = 0.50 IoU(a,b) + 0.30 C + 0.20 Z
~~~

If both `C` and IoU are zero, the pair scores zero. Candidate boxes use confidence threshold 0.25, NMS IoU 0.5 and at most 20 boxes per class. Hungarian matching maximizes positive pair scores. Unmatched reference instances score zero. The class mean is multiplied by `N_ref / max(N_ref, N_candidate)` to penalize extra instances, then frozen class weights are applied.

Contract-specific reflection handling can exclude a detected mirror instance only when at least 90% of its box lies in the identified mirror region. Task-specific boundary decisions still apply.

Localization measures 2D layout. It does not universally measure wall angles, room topology, true camera scale or unseen geometry. RealPhoto tasks without native references do not provide a complete 3D error target.

## Data and numeric requirements

Native Text2Code uses [l1_l2_alignment.measure_data](../../../src/evaluator/l1_l2_alignment.py): average available scores from the frozen `alignment.json/automatic_checks` list. Checks can include part inventory, closure, connectivity, solid validity and hierarchy. `unverified_requirements` and `pending_numeric_requirements` identify coverage gaps.

Native Brief2Scene uses task collectors and [l2_method_scoring.py](../../../src/evaluator/l2_method_scoring.py). The fixed population comes from `methods.json/active_checks`, `eval_spec.json` and the report measurements. Checks can include counts, dimensions, routes, access, contact and scene structure. Read the actual component list rather than interpreting the entire data score as complete geometric correctness.

Extension Brief uses [measure_effort_addition_numeric.py](../../../tools/measure_effort_addition_numeric.py). An agent helps select semantic entities and organize trusted Blender measurements. [audit_new_task_constraints.py](../../../tools/audit_new_task_constraints.py) verifies units, the measurement ledger, numeric JSON pointers and source bindings. Final arithmetic is:

~~~text
data = number_of_satisfied_entries / number_of_frozen_native_content_checks
~~~

Accepted `violated`, `partial`, `observed` and `not_measurable` entries remain in the fixed denominator; unresolved entries are recorded. API failure, failed ledger validation or an incomplete review blocks the review output.

## SceneEdit

[l2_edit_target_scoring.py](../../../src/evaluator/l2_edit_target_scoring.py) measures target changes. For geometry-edit mode:

~~~text
target = 0.60 surface + 0.25 regions + 0.15 structure
surface = 0.50 target_projection_IoU + 0.50 visible_target_point_coverage
~~~

Visible-point coverage compares candidate hits against reference world points on fixed main-camera pixels, using an exponential distance kernel with scale 3% of the reference point-set diagonal, floored at `1e-7 m`. Regions average the frozen target regions. Structure checks explicit thickness, cavities and related requirements.

Preservation covers protected objects, camera, fixed lighting, world and render/frame settings. Legitimate shadow/reflection changes caused by the requested edit are allowed by the contract. Lighting edits have separate property/illumination measurements, rather than the geometry formula above. Read final `component_weights`: intermediate `similarity_weight` and `target_weight` can have different scopes.

## Visual judging and detail

[l2_rubric.py](../../../src/agent_judge/l2_rubric.py) assigns frozen criteria integer grades 0–4, from absent/wrong/unproven through evidence-supported fulfillment:

~~~text
V = sum(w_i * grade_i/4)
~~~

| Family | Rubric groups |
| --- | --- |
| Text2Code / Brief2Scene | Instruction 60%, aesthetics 40% |
| Reference reconstruction | Shape/identity 40%, layout/multiple views 30%, appearance 30% |
| SceneEdit | Edit fulfillment 50%, target similarity 30%, preservation 20% |

These are internal rubric weights, multiplied by the final VLM coefficient. Native L2 uses [l2_fidelity.py](../../../src/agent_judge/l2_fidelity.py), requiring achieved features, largest discrepancy and severity. Maximum grades for `none/minor/major/wrong_or_absent/not_demonstrated` are 4/3/2/0/0. Inconsistent responses are rejected.

[task_continuous.py](../../../src/agent_judge/task_continuous.py) provides detail coverage `c` and deviation `e`, with `q=c*(1-e)`. Zero coverage requires zero deviation; confidence is separate. Required technical evidence failure remains missing. [measure_interactive_detail.py](../../../tools/measure_interactive_detail.py) adds native hinge/strut kinematics for Image2Code_008 over its complete frozen frame population.

Packets separate candidate, public reference and diagnostic evidence. Judges do not see other candidates or prior scores. Text creation has no private example target; SceneEdit receives before/target context. Retries repair transport, schema or evidence failures, and accept the first valid judgment regardless of score. Ordinary native detail uses a single-round cached request profile; extension detail can use a different compact multi-round configuration. The required variant population remains fixed.

Different internal protocols can use different kernels, including squared deviation. Use the formula selected by the final task contract. [L3 v5](l3.md) assigns evidence-based quality directly and does not reuse the L1/L2 coverage/deviation product. Judge identity limitations are in [Results](../results.md#judge-configuration).
