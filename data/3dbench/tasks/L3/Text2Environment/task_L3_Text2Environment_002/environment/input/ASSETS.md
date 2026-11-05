# Offline asset library

All assets below are mounted read-only before generation. Search, select, adapt or create materials and geometry freely; the library is optional and does not prescribe your visual style. Reference images are visual targets, not textures to project over proxy geometry.

- `/assets/polyhaven`: 869 complete 2K PBR texture sets, 4,388 files, CC0. Powered by Poly Haven. Manifest contains texture paths, hashes, normal-map conventions and source credits.
- `/assets/models`: seven Kenney CC0 packs, 1,015 distinct models with FBX, OBJ and glTF variants. Furniture, food, vegetation, industrial, survival, castle and space assets. Manifest records all bytes and licenses.
- `/assets/kenney`: 85 CC0 voxel textures, also pre-imported under `/Game/L3Materials/Kenney`. These are optional, including for non-voxel tasks.
- UE built-in basic geometry and the supplied daylight/sky setup are available. No account login or network download is needed.

`asset-selection.json` lists useful material IDs and model families for this task; the full libraries remain accessible. Models are individual props/modules, not a furnished solution scene or a gameplay implementation. Apply suitable scale, collision and materials, and author task-specific geometry and interactions yourself.

Search: `python3 /opt/l3-public/l3_assets.py search "wood" --type material`

Search models: `python3 /opt/l3-public/l3_assets.py search "chair" --type model`

Import: `python3 /opt/l3-public/l3_assets.py import-models --output /workspace/checks/props-001 furniture-kit/chair`

Materials: `python3 /opt/l3-public/l3_assets.py import-materials --output /workspace/checks/materials-001 MATERIAL_ID`

Each import writes its log, exact UE object paths and mesh bounding-box half extents in centimetres to the output folder. Source model scales vary across packs: choose the intended real-world dimensions and scale placed actors accordingly; do not assume unit actor scale is appropriate. Use a fresh folder. Build the starter once before importing. Imported source models may be static assemblies; split or rebuild articulated parts when required. Record actual usage and transformations in project/assets_used.json.
