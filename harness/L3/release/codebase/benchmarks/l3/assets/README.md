# L3 offline materials

Materials are prepared by the organizer, before generation. Trial execution must not invoke the download tool or fetch additional assets.

## Poly Haven snapshot

The catalog snapshot `polyhaven-catalog-2026-10-16.json` contains 869 texture entries returned by the official API. Powered by Poly Haven: https://polyhaven.com/our-api . Assets are CC0; provider metadata and website preview images are not automatically licensed as CC0. This preparation does not download website preview images or mesh assets.

```sh
python tools/prepare_l3_materials.py plan --input benchmarks/l3/assets/polyhaven-catalog-2026-10-16.json --output /assets/polyhaven-2k --workers 2
python tools/prepare_l3_materials.py fetch --input /assets/polyhaven-2k/plan.json --output /assets/polyhaven-2k --workers 4
python tools/prepare_l3_materials.py verify --input /assets/polyhaven-2k/manifest.json
```

The 2K profile contains JPEG base color, lossless data maps when available, and per-map normal conventions. It includes base color, normal, roughness and available metallic/AO/height/opacity/mask maps. It is a standard PBR subset, not an exact reproduction of each provider's Blender shader graph. For multi-color variants the selected source channel is recorded; additional variants and anisotropy/translucency shader graphs are not included.

`plan.json` locks source URLs, sizes and upstream MD5 values; `manifest.json` additionally locks every downloaded file with SHA256. Failed or partial preparation cannot pass verification. Resume with the same plan rather than refreshing assets in a trial. Record the manifest hash outside the agent workspace and mount the completed pack read-only. Preserve provider credit and asset authors in the catalog.

## UE import

`tools/ue_import_l3_materials.py` runs in a project with `PythonScriptPlugin` and `EditorScriptingUtilities` enabled. It imports an explicit subset into `/Game/L3Materials/<id>/`, checks source hashes, applies sRGB only to base color, imports normals with their recorded convention and connects standard PBR channels. Height and provider-specific masks remain raw authoring inputs; the importer does not invent displacement or transparency semantics.

Write an import configuration:

```json
{"manifest":"/assets/polyhaven-2k/manifest.json","ids":["wood_planks"],"report":"/workspace/import-report.json"}
```

Run with the pinned engine in the prepared isolated environment:

```sh
L3_MATERIAL_IMPORT=/workspace/import.json "$UE5_ROOT/Engine/Binaries/Linux/UnrealEditor" /workspace/project/Scene.uproject -run=pythonscript -script=/tools/ue_import_l3_materials.py -NullRHI -unattended -nosound -nop4 -DDC=NoZenLocalFallback -corelimit=4
```

Import success verifies asset creation and parameter wiring, not rendered visual quality. Run visual QA before freezing a public environment. Cache/import common assets before the generation timer where feasible. Ship the raw maps, searchable manifest and preimported project-independent content together; the agent may choose or adjust materials without solving an asset-download task.

## Voxel supplement

[Kenney Voxel Pack 1.0](https://kenney.nl/assets/voxel-pack) supplies a CC0 supplement. The organizer selection is `PNG/Tiles/*.png` (85 textures) plus the original `License.txt`; source archive hash and individual file hashes are retained. Sample scenes, layouts, characters and screenshots are excluded from the trial pack. These are stylized 2D surface graphics, not Minecraft's original textures or a comprehensive pixel-perfect replacement. A strict reference task must use compatible material inputs on both reference and candidate sides.

## Publication boundary

The shared storage copy is preparation data. A formal Harbor environment must explicitly mount the fixed pack, expose its catalog/tooling and pass engine/build/preview health checks. Merely storing files on the host does not make them available to an agent. Full-scene geometry, object transforms and interaction implementations remain verifier-only. See `docs/L3_Agent_Assets_Protocol.md` for trial and scoring rules.
