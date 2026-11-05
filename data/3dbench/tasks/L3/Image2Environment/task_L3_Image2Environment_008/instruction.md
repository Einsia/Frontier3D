# Overwatch: Rialto Canal Plazas and Service District

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the Overwatch Rialto canal-side district in the reference images as a polished, stylized environment. Connect the canal plaza, shopping street, side alleys, warehouse and elevated walkway. Match the references' architecture, colours, clean material separation, readable silhouettes and scenic background. Complete the main street route and an alternative elevated route, and furnish the warehouse, a small shop and a maintenance room. The environment should read as a complete game location at both street level and from an overview.

## Interactive environment

Make the maintenance panel control district service power. Power enables two warehouse shutters and a two-stop freight lift; loss of power stops motion in place, and restoring power allows explicit continuation. Lift doors remain closed between landings. A movable cargo platform follows the street route, stops at a closed barrier or obstacle and can resume when clear. It must carry actual crates. A dock latch secures the delivered platform. Implement these as task-specific logistics interactions; weapon systems and multiplayer gameplay are outside scope.

## End-to-end activity

Restore service power in the maintenance room, open the warehouse, use the lift to retrieve two upper-storey crates, load the street platform, clear the route and deliver to the dock. Secure the platform, unload the crates and verify their new locations.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
