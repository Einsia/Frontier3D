# Cheung Chau Ferry Terminal and Market Service Area

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the photographed Cheung Chau ferry terminal, shoreline, quay levels, canopies and surrounding waterfront character. Complete the waiting hall and add a coherent adjacent market, service lane and warehouse. Connect the waiting area to a fixed docked ferry through a gangway, and connect market deliveries to the warehouse without blocking passenger access. Include seating, signs, bollards, railings, ropes, stacked crates and weathered coastal materials. Complete the waiting hall, several market stalls and warehouse interior.

## Interactive environment

Implement two boarding gates, an adjustable gangway, three stall shutters, two retractable awnings and a delivery cart. The gangway has stowed and deployed states; boarding gates open only after deployment and close before retraction. The deployed surface and railings allow the player to reach the stationary ferry. Shutters and awnings physically clear the stall goods. Six cargo units can be transferred from the warehouse to three distinct stalls, two per stall. The ferry remains fixed; navigation and tide simulation are not required.

## End-to-end activity

Load six units at the warehouse, open the stalls and deploy their awnings, then deliver two units to each stall. Deploy the gangway, open boarding access and walk onto the stationary ferry and back. Close boarding access, stow the gangway and return the empty cart.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
