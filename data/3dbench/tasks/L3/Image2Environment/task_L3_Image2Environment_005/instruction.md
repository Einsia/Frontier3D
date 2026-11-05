# Recreate a Minecraft village

Recreate the entire open-world Minecraft environment shown in the supplied reference image in Unreal Engine 5, with the village as the focal area for detailed modeling and interaction. Match the image's overall appearance, building shapes and arrangement, terrain, materials, lighting and Minecraft style. Reproduce the surrounding landscape, vegetation and distant scenery as part of the same coherent environment. Make the village convincing when explored on foot, and infer unseen surroundings and interiors consistently with the reference. The scene should have a sensible layout, with grounded objects, usable paths and no unintended intersections.

Include furnished, accessible buildings and working doors, chests, a livestock gate, crops that can be harvested and replanted, editable blocks, and a furnace. Interactions must visibly affect the scene, obey collision and normal gameplay rules, and preserve state while the player travels around the village.

The scope and gameplay requirements are in `input/REQUIREMENTS.md`; the supplied interface and submission format are in `input/INTEGRATION.md`. Use the offline material library or create and adapt your own materials as appropriate. Deliver a complete runnable project, and inspect your renders and interactions while developing it.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
