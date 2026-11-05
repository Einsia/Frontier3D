# Orchestrator

Public end-to-end entry point: python -m benchmark run --task TASK --output runs/NAME.
See [installation and running](../docs/installation.md) for installation,
configuration, batch execution and resume.

The modules in this directory manage model-visible task staging, bounded model
calls, first-success source selection, isolated Blender execution, fresh seeds,
trusted execution records and evidence. Task harnesses own specifications;
src/evaluator owns measurement/scoring algorithms; src/agent_judge owns blinded
visual/native inspection.

python -m orchestrator list --level 1 and --level 2 expose the native-harness
inventory. Extension tasks are routed by benchmark/engine.py.
