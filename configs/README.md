# Runtime configuration

This directory contains the configuration used by the released benchmark:

| Directory | Purpose |
| --- | --- |
| `release/` | Frozen task mappings, scoring contracts, model harnesses, generation budgets and level aggregation. |
| `evaluation/` | Candidate partial-credit policy and native render recovery policy used by current scoring routes. |

`benchmark.resources` reads `release/index.json` and materializes portable
contracts into each campaign. Some current scoring contracts retain dated
method identifiers; their reference inputs, detail rules and weights remain
part of the released scoring definition.

The unused 101-task continuous evaluation package and standalone L2 entity
physics experiment have been removed along with their dedicated workflows.
Shared scene rendering and inspection live in `tools/scene_render.py`,
`tools/saved_scene_render.py` and `tools/native_scene.py`.
