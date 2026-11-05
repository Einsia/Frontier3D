# Recreate a Minecraft village

Recreate the entire open-world Minecraft environment shown in the supplied reference image in Unreal Engine 5, with the village as the focal area for detailed modeling and interaction. Match the image's overall appearance, building shapes and arrangement, terrain, materials, lighting and Minecraft style. Reproduce the surrounding landscape, vegetation and distant scenery as part of the same coherent environment. Make the village convincing when explored on foot, and infer unseen surroundings and interiors consistently with the reference. The scene should have a sensible layout, with grounded objects, usable paths and no unintended intersections.

Include furnished, accessible buildings and working doors, chests, a livestock gate, crops that can be harvested and replanted, editable blocks, and a furnace. Interactions must visibly affect the scene, obey collision and normal gameplay rules, and preserve state while the player travels around the village.

The scope and gameplay requirements are in `input/REQUIREMENTS.md`; the supplied interface and submission format are in `input/INTEGRATION.md`. Use the offline material library or create and adapt your own materials as appropriate. Deliver a complete runnable project, and inspect your renders and interactions while developing it.


## Workspace
Work in /workspace/project. The compiled starter is a generic lighting and material test fixture, not part of the village. Replace its test geometry. L3DefaultEnvironment.h provides L3AddDefaultDaylight(World), a reusable sky and lighting setup; you may call it or supply your own environment. UE5_ROOT points to the installed engine. Read input/ASSETS.md, input/REQUIREMENTS.md and input/INTEGRATION.md. Kenney materials are imported under /Game/L3Materials/Kenney; exact paths are in kenney-import.json. Poly Haven materials are available at /assets/polyhaven. The library is optional; you may adapt or create materials. Kenney materials expose a scalar UVScale parameter, default 1, for your own material instances.

Build: python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16
Add --blueprints when changing Blueprint assets. The default checks C++ without repeatedly compiling engine Blueprint content. Independent final validation is separate.
Preview: python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z
Use a fresh output directory for each invocation. View the supplied reference and your rendered PNGs with image tools. Iterate independently until the complete deliverable is ready, including model calls, edits, builds and previews. The clock starts after equipment and connection checks. Finish with the project, bindings.json, assets_used.json, README and genuine final previews. Network access is disabled except for the model service.
