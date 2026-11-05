# Outer Wilds-inspired Hydraulic Alien Ruins

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create an Outer Wilds-inspired alien hydraulic ruin: an approximately 240 by 180 metre valley complex with an upper reservoir, a central ring-shaped courtyard, two lower water basins, underground channels, a control chamber and an observation terrace. Connect the terraces with stairs, walkways and eroded stone passages. Use ancient pale stone, patterned metal mechanisms, luminous symbols, weathering and vegetation to make the water system's purpose legible. Furnish the control chamber, a maintenance chamber and a small archive with coherent instruments and artefacts. The ruin should feel embedded in a larger landscape.

## Interactive environment

Use two independently controlled basins, each with a visible low and high water level. An inlet valve and drain gate govern each basin; filling requires an open inlet and closed drain. A floating platform follows basin A's level and carries the player to an upper walkway. Basin B's low level exposes a dry lower passage, while its high level makes a second floating crossing usable. Include a power switch for the inlet pump, animated valve wheels and moving sluice gates. Water levels change gradually with visible flow cues; deterministic animation is sufficient, with no requirement for fluid simulation or underwater locomotion.

## End-to-end activity

Begin with both basins low and the pump off. Reach the control chamber through the lower route, enable the pump, fill basin A and ride the platform upward. Fill basin B to cross to the observation terrace, open its drain from the far side, then return through the exposed lower passage. Revisit basin A and preserve its independently set level.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
