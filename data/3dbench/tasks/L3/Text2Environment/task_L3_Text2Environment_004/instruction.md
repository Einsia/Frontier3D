# Breath of the Wild-inspired Frontier Valley

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a Breath of the Wild-inspired frontier valley of approximately 320 by 240 metres, with a stable and travellers' lodge at the centre, a river and wooden drawbridge, a woodland camp and ruins on a rocky rise. Use a bright painterly style, expressive foliage, warm timber, weathered stone and a readable daylit sky. Shape the terrain into a navigable valley with paths, riverbanks and scenic hills. Furnish the lodge, stable service room and camp, and make the ruins an explorable destination with a supply chamber.

## Interactive environment

A movable counterweight activates a pressure plate only while physically supported by it. The active plate enables a winch that lowers and raises the river bridge. Provide a two-stop lift at the ruins, a stable gate, an opening tool chest and three collectible supply bundles. The lift carries both the player and a supply crate. Removing the counterweight disables further winch movement but does not teleport or reset the bridge. Moving the bridge and lift must keep their geometry, collision and supported objects together. Horses and wildlife may be static scenery.

## End-to-end activity

Take tools from the stable chest, find and place the counterweight from the camp, lower the bridge and cross to the ruins. Raise a crate using the lift, collect three supplies in it, bring the loaded crate back to the lodge and store the tools. Leave the world in the resulting state.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.


# L3 generation and delivery contract

Build a complete, editable and runnable UE5 project. The actual generation input is the English task statement together with this contract and the supplied task inputs. Use the offline asset library where appropriate; adapting materials or making your own is allowed. Record asset provenance. Do not download assets during the task or import a complete solution scene.

Implement a controllable character using the supplied public interaction components. Manual controls and automated actions must call the same gameplay logic. Interaction must move actual geometry, update collision and preserve object identity and state within the session. Reject unavailable, out-of-reach or occluded operations. Make required paths traversable, objects supported and moving parts clear of unintended intersections. Cross-process persistence is not required.

Autonomously compile, run, inspect multi-view renders and test interactions. The harness records elapsed generation time, model, resource budget and reported token usage, including retries. The task-specific runtime configuration defines the time budget. Deliver project/, source and required assets, README.md, assets_used.json, interface bindings and genuine final previews covering the overall scene, each functional zone, an interior and key interactions. Document startup, controls, initial state, action prerequisites and limitations.

The scene's appearance must remain coherent across all views, with suitable scale, geometry, material assignment, textures, lighting and sky or background. For image tasks, use the supplied images as the visual target and infer unseen areas coherently. Added interaction fixtures must fit the environment. For text tasks, design the layout from the brief; there is no hidden reference image.
