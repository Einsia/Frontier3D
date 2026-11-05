# Embodied Environment: Furnished Kitchen and Utility Suite

Recreate the furnished kitchen and dining corner in the supplied photographs, matching the cabinets, worktops, refrigerator, appliances, blinds, table, small household objects and warm light. The four views come from one real room. Make the room fully explorable and complete a compact connected utility room, entrance hall and garden-tool store consistently with it. These adjoining spaces are a design extension, not additional photographed rooms. Give cupboards, drawers and appliances usable interiors and working clearances. Keep the density and character of the photographed kitchen while allowing a person carrying a basket to move through it.

## Interactive environment

Implement two room doors, two drawers, two cupboard doors, a refrigerator door and a washing-machine door. Supply two garments, a plate, a cup, a detergent bottle, a garden tool and a transport basket as distinct movable objects. The basket retains its contents while carried or placed. A kitchen tap visibly turns water on and off. The washer starts only with both garments loaded, one detergent dose added and its door closed. Its short cycle locks the door until finished, then allows unloading. Adding detergent consumes one of the bottle's three doses without destroying the bottle.

## End-to-end activity

Take the basket from the utility room, collect both garments from the utility shelf, load and run the washer, put the plate and cup into kitchen storage, and carry the garden tool to its store. Return to unload the finished laundry into the basket. Keep all item identities and resulting states consistent.

Create a detailed, coherent environment with sensible layout, stable placement and clear visual interaction feedback. Inspect appearance and behaviour during development and follow the supplied delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
