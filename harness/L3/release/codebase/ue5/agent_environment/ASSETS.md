# Offline material library

These assets are fixed before the task begins. You may search, select, import and modify them, or create your own materials. Do not download assets during the trial.

| Directory | Contents | License |
|---|---|---|
| `/assets/polyhaven` | 869 sets of 2K PBR materials, 4,388 texture files | CC0, Poly Haven |
| `/assets/kenney` | 85 voxel surface textures from Kenney Voxel Pack 1.0 | CC0 |

Each directory has a manifest.json with paths and hashes. Record attribution and actual usage in project/assets_used.json. Poly Haven includes wood, brick, stone, ground, metal, wall and fabric categories. Powered by Poly Haven.

The public /opt/l3-public/ue_import_l3_materials.py importer supports selected Poly Haven materials. Read its configuration format and supply L3_MATERIAL_IMPORT for the enabled UE PythonScriptPlugin and EditorScriptingUtilities. The manifest specifies normal-map conventions; height and mask channels may require custom material connections.

Kenney materials are pre-imported under /Game/L3Materials/Kenney/M_<name>; kenney-import.json lists exact asset paths. They use nearest-filtered textures and expose the scalar parameter UVScale (default 1). You may create dynamic or saved material instances and set UVScale, edit material graphs, use different faces or author your own textures. These are surface textures, not complete block meshes or original commercial Minecraft assets.

The library supplies no village geometry, building prefabs or gameplay. It does not constrain your geometry, material choices or scene design. Include only assets actually needed by the project and describe sources, UE paths and transformations in assets_used.json.
