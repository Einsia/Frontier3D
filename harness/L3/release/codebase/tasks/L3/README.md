# Native L3 task inputs

The supported release contains 15 tasks. Its authoritative task index and runbook
are [../../../task-index.json](../../../task-index.json) and
[../../../README.md](../../../README.md).

The native generation schema uses `task.json`, `PROMPT.md`, `runtime.json`,
`environment/input/`, and `package-manifest.json`. These frozen inputs are kept
separately from the Harbor wrappers under the public repository's
`data/3dbench/tasks/L3/Text2Environment/` and
`data/3dbench/tasks/L3/Image2Environment/`. The wrapper instructions include the shared
Harbor delivery contract. The runner selects the native `generation_ready`
task matching each release key.

`MinecraftVillageOpenWorld` supplies `l3-g01`. The 14 other generation-ready
native packages supply the remaining release tasks; `task-index.json` in this
native directory describes those 14 original templates. Earlier Minecraft pilot
and PlayableGame definitions are retained as schemas and compatibility inputs.
They are not additional tasks in the active 15-task release.

The native `runtime.json` records original template model/effort defaults and
source library provenance. Actual model/effort and external asset paths come
from the campaign settings and exported runtime environment in the release
runbook. Task file hashes remain frozen; private credentials and previous trial
state are not included here.
