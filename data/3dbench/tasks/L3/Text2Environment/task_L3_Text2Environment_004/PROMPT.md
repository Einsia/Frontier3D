# Breath of the Wild-inspired Frontier Valley

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a Breath of the Wild-inspired frontier valley of approximately 320 by 240 metres, with a stable and travellers' lodge at the centre, a river and wooden drawbridge, a woodland camp and ruins on a rocky rise. Use a bright painterly style, expressive foliage, warm timber, weathered stone and a readable daylit sky. Shape the terrain into a navigable valley with paths, riverbanks and scenic hills. Furnish the lodge, stable service room and camp, and make the ruins an explorable destination with a supply chamber.

## Interactive environment

A movable counterweight activates a pressure plate only while physically supported by it. The active plate enables a winch that lowers and raises the river bridge. Provide a two-stop lift at the ruins, a stable gate, an opening tool chest and three collectible supply bundles. The lift carries both the player and a supply crate. Removing the counterweight disables further winch movement but does not teleport or reset the bridge. Moving the bridge and lift must keep their geometry, collision and supported objects together. Horses and wildlife may be static scenery.

## End-to-end activity

Take tools from the stable chest, find and place the counterweight from the camp, lower the bridge and cross to the ruins. Raise a crate using the lift, collect three supplies in it, bring the loaded crate back to the lodge and store the tools. Leave the world in the resulting state.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
