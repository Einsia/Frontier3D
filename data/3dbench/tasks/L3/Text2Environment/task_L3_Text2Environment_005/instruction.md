# Regional Rail Station and Intermodal Forecourt

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a realistic regional railway station and intermodal forecourt, approximately 280 by 210 metres. Include a station entrance plaza, ticket hall, waiting hall, two platforms connected by an elevated concourse, a bus stop, taxi rank, bicycle parking, small retail units and a service yard. Provide stairs and a two-stop lift between the ground-level concourse and elevated passage, with an accessible route continuing to the platform. Use coherent wayfinding, canopies, seating, railings, ticket equipment, luggage and maintenance details. The architecture should suit a modest regional city rather than a megacity terminal.

## Interactive environment

Provide a ticket terminal, two physical ticket gates, the two-stop lift, a luggage cart, six movable bags, opening luggage lockers and a service shutter. The terminal issues a ticket that authorizes passage without creating extra tickets on repeated collection. Gates visibly open and close and reject invalid access. Lift doors open only at the present landing and the cabin carries the player and loaded cart. Lockers accept and release actual bags. The service shutter opens a separate cart return route. Train operation, passenger AI and real payment are outside scope.

## End-to-end activity

Collect six bags at the taxi rank and load the cart. Obtain a ticket, pass the gate and lift, and reach the platform via the accessible route. Store two bags in lockers and deliver four to the platform luggage bay. Retrieve one stored bag, return via the service route and park the cart with that bag still on it.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
