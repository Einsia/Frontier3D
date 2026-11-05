# 旷野之息风格：驿站、废墟与山谷生活区

Task: l3-g06. Public inputs: instruction.md, COMMON.md, environment/input/.
Chinese statement: instruction.zh.md. Runtime contract: runtime.json.
Submission: editable UE project with Content, Source, Config, Plugins, .uproject,
bindings.json, assets_used.json, README.md, and genuine final previews.

Harbor layout: task.toml, environment/Dockerfile, tests/test.sh.
Execution requires the provisioned UE host backend documented in
harness/L3/release/README.md. A generic Docker-only Harbor worker is insufficient.
The licensed engine, offline asset libraries and private judge configuration are
external runtime dependencies. The host verifier creates fresh independent
evidence and writes reward.txt only after a complete v5 result.
Infrastructure failure produces an error, never a fabricated zero reward.

Scoring weights: visual quality 60%, substantive task fidelity 20%,
layout 5%, interaction 15%. Fixed task specification:
harness/L3/release/scoring-specs/l3-g06/spec.json.
