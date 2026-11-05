# Embodied Environment: Ward and Supply Corridor

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a realistic, unoccupied hospital ward for embodied logistics, occupying approximately 60 by 45 metres on one level. A loop corridor connects six patient rooms, two shared bathrooms, a nursing station, a clean-supply room, a utility room and a cart parking recess. Each patient room contains a bed, bedside cabinet, chair, curtain, handwash point and wall services. Use clean institutional materials, readable room signs, plausible lighting and varied furnishings. Corridors and doorways must accommodate the supplied cart, including turns and passing door leaves.

## Interactive environment

Implement room doors, two locked supply cabinets, six bedside drawers, a movable curtain, a supply cart and one adjustable empty bed. A keycard unlocks the supply cabinets. Stock six towel packs and six empty containers as individually movable objects. The cart carries them without changing identity. The bed's head section and overall height are independently adjustable with attached parts moving consistently. Taps have visible on/off states. Clean supplies and returned containers have separate storage locations. Do not simulate patients, diagnosis or treatment.

## End-to-end activity

Collect the keycard at the nursing station, load six towel packs and deliver one to each bedside drawer. Adjust the empty bed in room 3 and open its curtain. Collect a container from each room, return them to the utility room, then return the card and park the empty cart.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
