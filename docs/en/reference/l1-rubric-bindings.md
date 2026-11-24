# Native L1 rubric instruction bindings

The public release through commit `73c3b2c` contains stale `vlm_spec_digest`
values in 41 of the 45 native L1 alignment plans: all 15 Image2Code tasks,
all 15 Image2Code-SingleView tasks, and Text2Code 002–012. The real
`judge_aligned` validation rejects these tasks before calling a judge.
Text2Code 001 and 013–015 have matching digests.

During release preparation, scoring notes were removed from candidate-visible
instructions. The corresponding `instruction_sha256` inside each affected
`vlm_spec.json` was updated, but the enclosing canonical JSON digest in the
alignment plan was retained from the historical instruction. That digest covers
the entire rubric, including `instruction_sha256`.

Comparison with the retained `l1_strict_review_20261011_v2` plans found that all
45 historical rubric digests matched their historical plans. The 41 affected
released rubrics differ from those historical rubrics only in
`instruction_sha256`. Checklist text, weights, anchors, focus and localization
are identical.

The historical and released bindings are recorded in
[l1-rubric-bindings.json](../../../configs/release/l1-rubric-bindings.json).
To check the historical digest, replace only `instruction_sha256` in a released
rubric with `historical_instruction_sha256` and apply
`src.evaluator.l1_l2_alignment.digest`. This establishes the scope of the
binding repair; it does not make the historical and released instructions
byte-identical or rerun historical scores.

The baseline uses `3dbench-l2-rubric-v2`. The reference tasks use the frozen
ten-check strict rubric, including `cross_view`; the three-check `rubric()`
helper is an initial draft builder and does not reconstruct those final
reference rubrics. The released JSON files are the runtime scoring definitions.
The four task-specific final component overrides remain as documented in
[Scoring](../scoring.md#task-specific-overrides).

Run the read-only check from the repository root:

```sh
python scripts/verify_l1_rubrics.py
```

The same check runs when materializing campaign contracts, in
`doctor --resources-only`, and before updating the release manifest. It checks
all 45 task identities, instruction/source hashes, rubric schemas, reference
annotation bindings, canonical digests and mirrored plans.

For release maintenance, the following command repairs only the recorded
historical-to-release instruction binding. It refuses rubric text changes and
does not call a model or regenerate visual annotations:

```sh
python scripts/verify_l1_rubrics.py --rebind-instruction-digests
```

Use a fresh campaign after updating the release. Existing campaign resource
hashes and accepted reports remain immutable; a resume with changed contracts
is rejected.
