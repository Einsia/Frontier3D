# Scoring

[中文](../cn/scoring.md) · [Documentation](../README.md)

`python -m benchmark run/generate/evaluate` covers all three levels. Final item reports are written to `main_results/<model>/<task>/report.json`. `S_core` is in `[0,1]`; multiply by 100 for a percentage score. Level means and the 30/30/40 total are defined in [Tasks](tasks.md).

## Evaluation flow

1. Generate source and validate the public delivery contract. Repair feedback contains execution errors, without private scoring feedback.
2. Freeze accepted source and generation records. Evaluation uses that same candidate. A caller-supplied source is identified by `provided_source`.
3. Execute in isolation and collect saved scenes, required images, exports, dependencies and execution seeds. L3 independently builds, renders and replays the frozen UE project.
4. Measure the configured native, image, visual-judge and detail components. L1/L2 has 84 native-harness tasks and 46 extension tasks.
5. Verify source, rules, references, artifacts and judge bindings; aggregate complete measurements and export the final report.

`run --all` generates and evaluates each task in sequence. `generate --all` followed by `evaluate --all --resume` completes generation before evaluation. Intermediate native reports, `S_vlm` and screening scores are separate from the final item score.

## Item weights

| Task family | Final formula |
| --- | --- |
| Text2Code, Brief2Scene | `0.60 vlm + 0.30 data + 0.10 detail` |
| Image2Code, SingleView, Reference2Scene, RealPhoto | `0.50 main_image + 0.20 localization + 0.20 vlm + 0.10 detail` |
| SceneEdit | `0.20 numeric + 0.30 target + 0.20 preservation + 0.20 vlm + 0.10 detail` |
| L3 environments | `0.60 visual_quality + 0.20 task_fidelity + 0.05 layout + 0.15 interaction` |

| Component | Measurement |
| --- | --- |
| `data`, `numeric` | Task-specific geometry, counts, parameters and implemented content checks; extension Brief uses an agent-assisted native measurement review |
| `main_image` | Fixed reference-image appearance algorithms; four task-specific overrides below use visual structure judgments |
| `localization` | Reference-owned object boxes, VLM candidate observations and deterministic matching |
| `target`, `preservation` | Requested edit and unchanged scene content, using native geometry or lighting checks |
| `vlm` | Frozen semantic, reference-fidelity, edit or aesthetic rubric |
| `detail` | Frozen local-shape and part-composition checklist; one task also measures mechanism motion natively |

See the English [metric reference](reference/metrics.md) and [L3 reference](reference/l3.md) for formulas. Exact per-task weights and checks are in the [L1/L2 inventory](../reference/scoring-task-inventory.json), [native rules](../../configs/release/linear-config), [extension rules](../../configs/release/addition-config) and [L3 specs](../../harness/L3/release/scoring-specs/manifest.json).

## Detail variants

The final L1/L2 combination replaces the baseline's 10% contact/support component with detail, retaining the other components and their weights. Original measurements remain in the report's replacement record. Execution, loading, dependency and material-validity checks still apply.

For frozen criteria `C` and required variants `P`:

~~~text
w'_i = w_i / sum(w_j for j in C)
q_(v,i) = coverage_(v,i) * (1 - deviation_(v,i))
D_v = sum(w'_i * q_(v,i) for i in C)
D = min(D_v for v in P)
~~~

Compute a complete detail value for each variant, then take the minimum variant. All atoms come from that same selected variant. Required technical missingness blocks the result; confirmed candidate defects can yield documented local zeros.

- The 45 native L1 tasks normally require primary plus three execution seeds, each in native/GLB form: eight variants.
- The 39 native L2 tasks normally require primary plus three seeds: four native variants. Exact seed IDs come from each contract.
- Extensions normally use the corresponding eight L1 or four L2 variants.
- `detail-only-v1` limits each judge checklist to counted atoms while preserving their definitions and weights. It does not reduce the variant population.

The public CLI uses the full frozen population. `LEGACY_DETAIL_VARIANT_LIMIT` has no effect on formal measurements. Explicit lower-level screening options produce separate diagnostic subsets; cached subsets cannot be reused or finalized as formal results. Inspect `required_variants` and `measured_variants` before comparing results.

## Task-specific overrides

Four native tasks use `direct-components-linear-r2`. Their final `main_image`, `vlm` and `detail` come from the following linear visual observations; baseline `localization` and final 50/20/20/10 weights remain.

| Task | `main_image` | `vlm` | `detail` |
| --- | --- | --- | --- |
| SingleView_001, shoe | `0.50 shoe_profile + 0.50 shoe_upper` | `shoe_laces` | `shoe_sole` |
| SingleView_009, horse head | `2/3 horse_profile + 1/3 horse_neck` | `horse_anatomy` | `horse_mane` |
| SingleView_010, David bust | `0.70 david_face + 0.30 david_bust` | `david_surface` | `david_hair` |
| Reference2Scene-005, city | `0.50 city_layout + 0.50 city_buildings` | `city_facades` | `city_roofs` |

Each atom uses `coverage * (1 - deviation)`. These overrides judge the bound baseline candidate and do not apply the ordinary eight/four-variant detail minimum. `final_override` in the inventory identifies this exception. Implementation: [legacy_detail_v2.py](../../src/evaluator/legacy_detail_v2.py).

## Validity and partial credit

| Result | Score treatment |
| --- | --- |
| Measured content defect, wrong proportions, absent required detail or poor exposure | Related quality terms can be low or zero; preserve other measured terms and fixed weights |
| Confirmed required-delivery violation, such as an unloadable scene or forbidden dependency | `score_valid=false`, `system_invalid` and `S_core=0`; include zero in the fixed task population and level mean |
| API failure, corrupt/missing technical evidence, binding mismatch or unimplemented measurement | Preserve missingness (`S_core=null` or `technical_failure`) and retain evidence |
| Signature, seed or submitted-image difference | Record a diagnostic and apply the route's evidence policy |

Delivery checks cover actual execution, required files, scene/GLB loading, editable geometry, image dimensions, dependencies and all required seeds. A passed system gate does not establish semantic task quality.

When a bound saved-scene rerender succeeds, the baseline and detail may use that authoritative image. The submitted PNG and mismatch remain in diagnostics. Rerendering retains the task's camera, frame and appearance policy; it does not repair candidate lighting or exposure. Seed geometry differences are separated from proven execution/loading failures. Missing seed evidence remains unresolved.

Reference-texture checks trace active material, world and compositor nodes, packed image hashes and UV coverage. A reference image merely stored in a scene is distinguished from active use. A full reference on a simple plane violates the modeling contract. Explicitly allowed local texture crops require supporting node/UV evidence; ambiguous large or wrapped crops require review.

The [candidate policy](../../configs/evaluation/candidate-robustness-v1.json) permits zeroing only affected checks with confirmed candidate-caused undefined content. It excludes API, filesystem, provenance and interrupted-infrastructure failures. Unknown crashes need diagnosis. Keep the original measurement snapshot and recovery reason.

Every positive-weight component requires a finite measurement. Do not fill technical failures with zero, redistribute missing detail weight or select the best judge retry. The extension Brief contract credits only `satisfied` entries over the fixed `native_content_checks` population; `violated`, `partial` and `observed` entries retain zero credit in that denominator. A `not_measurable` entry blocks the data component and final score, following the original missing-measurement policy. A failed or unbound review also blocks output.

## Example and interpretation

A valid ordinary reference task with image `0.60`, localization `0.50`, VLM `0.75` and detail `0.40` has:

~~~text
S_core = 0.50*0.60 + 0.20*0.50 + 0.20*0.75 + 0.10*0.40 = 0.59
~~~

That is 59/100. A missing required detail judgment leaves the total missing. A measured absent feature can receive zero normally.

Localization primarily measures 2D object layout; RealPhoto tasks lack a universal native 3D ground truth. Reference regions, perceptual weights and AI judgments retain calibration limits. Report fields such as `formal_score_eligible`, `human_calibrated` and `limitations` remain meaningful. Read component evidence alongside the total; see [Results](results.md).
