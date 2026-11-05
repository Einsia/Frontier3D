# Contributing

Use an isolated run directory. Install requirements-dev.txt and run
python -m pytest. Follow [validation](docs/installation.md#validate) before changing task contracts.

Keep generation inputs limited to the task's environment_files allowlist.
Never send hidden reference solutions, evaluator rules, or scores to a generator.
Preserve failed runs and accepted low scores. Technical measurement failure
must remain distinguishable from a confirmed model-content failure.

Metric changes need meaningful failing/correct pairs and a description of
affected components, weights, missingness, task scope, and version changes.
Do not silently reinterpret old reports or fit model-specific coefficients.

Task assets need source, attribution, redistribution terms, and hashes.
Do not commit credentials, model outputs, run archives, queues, or caches.
