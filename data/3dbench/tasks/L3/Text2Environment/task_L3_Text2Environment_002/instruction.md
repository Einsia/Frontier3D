# Embodied Environment: Water Treatment and Maintenance

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a realistic small water-treatment facility of approximately 180 by 130 metres. Include a raw-water tank, two parallel treatment lines, a clean-water tank, pump house, control room, parts store and elevated inspection platforms. Show understandable pipe connections, bends, supports, gauges and access points. Connect buildings and platforms with ground paths and stairs, with railings around tanks and elevated edges. Use weathered concrete, painted steel, pipes, wet surfaces and functional industrial lighting.

## Interactive environment

Each treatment line has an inlet valve, outlet valve and removable filter inside an opening maintenance housing. A pump switch supplies the system. Isolate both valves on a line and stop the pump before releasing that filter; otherwise opening the housing or removing it is refused. Provide one spare filter and a cart. Reinsert and latch a filter before restoring that line. Visible flow and tank inflow depend on pump state, valve connectivity and installed filters; the second line remains independently configured. Use a deterministic process model rather than chemical or full fluid simulation. These interlocks are a simplified task specification.

## End-to-end activity

Inspect the marked first line, stop the pump and isolate that line. Fetch the spare filter, replace the installed filter and carry the used one to the parts store's return bin. Close the housing, reopen the line and restart the pump; show restored inflow without changing the second line's valve settings.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
