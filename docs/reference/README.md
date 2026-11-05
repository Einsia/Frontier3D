# Machine-readable reference

[Documentation](../README.md)

These files describe task definitions and distribution metadata. They contain no candidate results. Human-readable guides are in [en/](../en/tasks.md), with core Chinese editions in [cn/](../cn/README.md). Detailed algorithms are in the English [metric](../en/reference/metrics.md) and [L3](../en/reference/l3.md) references.

| File | Contents |
| --- | --- |
| [task-index.csv](task-index.csv) | Current task identities and paths |
| [scoring-task-inventory.json](scoring-task-inventory.json) | Full frozen scoring definitions for all 130 L1/L2 tasks |
| [scoring-task-inventory.csv](scoring-task-inventory.csv) | Compact L1/L2 weights, routes and detail populations |
| [task-attribution-index.json](task-attribution-index.json) | Active-task credits, source notices and hashes |
| [asset-attribution-index.csv](asset-attribution-index.csv) | File-level attribution lookup |
| [release-manifest.json](release-manifest.json) | Packaged source paths and SHA-256 values |

Regenerate the scoring inventory from the repository root:

~~~sh
python scripts/export_scoring_inventory.py
~~~

Check distributed files and attribution with `python scripts/verify_release.py`. After reviewing changes to a release checkout, maintainers can refresh the file inventory with `--update-manifest`. Neither command calls a model. Per-task L3 scoring specs are under [harness/L3/release/scoring-specs](../../harness/L3/release/scoring-specs/manifest.json).
