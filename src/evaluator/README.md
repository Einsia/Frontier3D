# Evaluation implementation

The public pipeline is documented in ../../README.md. Frozen release contracts
live in ../../configs/release, materialized and hash-bound inside each run.
Algorithms in this directory execute in host Python or dedicated Blender
workers. Four-component image scores retain 50/20/20/10 weights; other categories
use their own versioned contracts.

Missing measurements remain distinct from confirmed model-content failures.
Visual judgment never feeds private scores or solutions back into generation.

See [the scoring documentation](../../docs/README.md) for the final public
pipeline, category weights, metric formulas, validity rules and task contracts.
Reports preserve source hashes, components, weights, coverage and evidence.
