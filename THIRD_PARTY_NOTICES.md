# Third-party assets and tools

Apache-2.0 applies to the benchmark software. Original task images, meshes,
Blender files, materials, CAD files and their source archives retain the
individual license terms shipped with each task.

The original CREDIT, LICENSE and provenance files are preserved. The complete
file index is [asset attribution index](docs/reference/asset-attribution-index.csv).
Consult the relevant task notice before redistributing or modifying an asset;
no blanket relicensing of third-party content is asserted here.

Blender and its Python modules are external runtimes under their upstream
terms. Codex CLI, Python dependencies and optional detector weights are
installed from their own distributions. No installed binaries, model weights
or Unreal Engine distribution is included.

The source-only examples are diagnostic integration fixtures. Frozen evaluator
rules and reference-only camera observations are evaluation specifications,
not previous model answers or benchmark scores.

Frozen external L3 library manifests and the Poly Haven plan are included under
`harness/L3/release/asset-locks/` for byte-verified acquisition. They retain their
source/author/license metadata; the asset libraries are downloaded separately.

The original Kenney CC0 source archives are included in
`harness/L3/release/asset-locks/archives/`. Each archive retains its upstream
license and notices, and the lock manifests retain its source and SHA-256.
Poly Haven texture bytes remain external downloads.

Every active L1/L2 task includes `attribution/CREDITS`, with its source task ID,
original attribution notice or provenance-based attribution, and license scope.
See [the task attribution index](docs/reference/task-attribution-index.json) and
[the current task license guide](docs/en/licenses.md). Task IDs and notices
refer to the active release.
Open permission/license questions in those records remain unresolved.
