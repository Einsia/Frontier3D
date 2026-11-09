# Frontier3DBench: Benchmarking Coding Agents for 3D Creation across Objects, Scenes, and Interactive Open Worlds

<p align="center">
  <a href="https://lab.einsia.ai/frontier3dbench/Frontier3DBench.pdf"><img src="https://img.shields.io/badge/Paper-PDF-B31B1B?style=flat-square" alt="Paper PDF" /></a>
  <a href="https://lab.einsia.ai/frontier3dbench"><img src="https://img.shields.io/badge/Project%20Page-Website-315F85?style=flat-square" alt="Project Page" /></a>
</p>

![Frontier3DBench overview: 145 tasks across objects, scenes, and interactive open worlds, with the model leaderboard](docs/img/main.png)

Frontier3DBench evaluates coding agents on executable 3D creation, from individual
objects and complete scenes to interactive open worlds. Agents generate editable
Blender scenes or runnable Unreal Engine projects from text, images, or existing
scenes, with reproducible code and required deliverables.

## Benchmark overview

The release contains **145 tasks** across three levels:

| Level | Scope | Tasks | Runtime |
| --- | --- | --- | --- |
| L1 | Object creation and reconstruction | 65 | Blender |
| L2 | Scene creation, reconstruction and editing | 65 | Blender |
| L3 | Interactive environments and open worlds | 15 | Unreal Engine |

Evaluation covers geometry, delivery, visual fidelity, local detail and
interaction. All three levels use the unified `python -m benchmark` interface.
The overall score combines level means with **30% / 30% / 40%** weights for
L1 / L2 / L3. See the [task guide](docs/en/tasks.md) and
[scoring guide](docs/en/scoring.md) for the evaluation contracts.

This repository includes task inputs, generation and evaluation code, scoring
contracts, and asset attribution. Model submissions, experiment outputs,
credentials and installed third-party runtimes are excluded. Candidate agents
receive staged task requirements and inputs; organizer scoring details and
reference-source attribution remain outside candidate workspaces.

## Documentation

- **[Installation and running](docs/installation.md)** — source checkout, Git LFS,
  dependencies, model providers, Blender/UE setup, generation, evaluation and resume.
- **[Documentation index](docs/README.md)** · **[中文文档](docs/cn/README.md)** —
  tasks, models, experiment settings, scoring and result exports.
- **[Agent instructions](AGENTS.md)** — workflow for an agent operating this benchmark.
- **[Security](SECURITY.md)** · **[Asset licenses](docs/en/licenses.md)** —
  execution boundaries and task-specific attribution.

## Citation

If you use Frontier3DBench, please cite:

```bibtex
@misc{lin2026frontier3dbench,
  title = {Frontier3DBench: Benchmarking Coding Agents for 3D Creation across Objects, Scenes, and Interactive Open Worlds},
  author = {Lin, Xinjie and Liu, Qingle and Li, Wenyi and Lam, John and Wang, Xiaoqiu and Hong, Deyao and Gao, Mingju and Jiang, Zheng and Chi, Yizhe and Zheng, Youjie and Xiao, Calvin and Yang, Kaisen and Gao, Huan-ang},
  year = {2026},
  eprint = {2611.09017},
  archivePrefix = {arXiv},
  primaryClass = {cs.CV},
  url = {https://arxiv.org/abs/2611.09017}
}
```

## License

Benchmark software is licensed under [Apache-2.0](LICENSE). Task assets retain
their individual licenses and attribution; see [third-party notices](THIRD_PARTY_NOTICES.md)
and the [asset license guide](docs/en/licenses.md). Blender, model CLIs and
Unreal Engine are installed separately.
