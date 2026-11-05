# Sekiro: Ashina Castle Keep and Connected Courtyards

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the Ashina Castle keep and the connected courtyards shown in the reference images as a richly detailed, explorable environment. Preserve the distinctive roof profiles, timber structure, stone base, floor heights, galleries, screens and courtyard relationships. Complete the visible exterior and the principal interior route, including an entrance hall, guard room, reception room and upper store room. Furnish these spaces with appropriate racks, containers, cushions, partitions and fittings. The keep is the focal point, with surrounding terrain and adjacent structures providing a coherent setting.

## Interactive environment

Make at least four sliding doors or screens operable along their tracks, including a pair that controls a passage. Provide an upper-level access route using stairs and a ladder with usable landings. A service lift must carry the player and a small crate between two floors; its landing barriers open only when the platform is present and stopped. Place a key in an opening storage box: collecting it enables a locked side door, and using the upper mechanism opens a courtyard shortcut. These are task-specific exploration interactions, not a requirement to reproduce the original game's combat or exact puzzle mechanics.

## End-to-end activity

Start in the outer courtyard, enter the keep, obtain the key, carry the crate to the upper store room using the lift, activate the upper mechanism, and return through the courtyard shortcut. Return to the storage box and confirm that the collected key is no longer there.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
