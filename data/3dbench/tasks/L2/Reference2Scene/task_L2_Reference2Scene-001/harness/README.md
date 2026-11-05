# Reference scene evaluation

## Scoring

Final item score: `50% main_image + 20% localization + 20% vlm + 10% detail`. Component definitions and evidence policies are in [Scoring](../../../../../../../docs/en/scoring.md).

Missing content, shape errors and layout differences reduce the relevant quality terms. Technical failures or missing required evidence leave the score unresolved; missing weights are never redistributed or filled with zero. Delivery, execution, loading, dependencies and integrity are checked separately under the task contract. Bound saved-scene rerenders provide scoring evidence; submitted images and mismatch diagnostics are retained.

Numerical checks cover implemented, evidenced measurements only. Unimplemented exact counts are not treated as satisfied. Visual observations do not certify hidden geometry, physical contacts or complete physical correctness. Reference regions and perceptual judgments retain calibration limits.
