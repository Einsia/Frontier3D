# Red Dead Redemption 2: Central Valentine District

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the Valentine town district shown in the reference images, with the main street, its side lanes, saloon, shops, stable yard and freight yard forming one explorable place. Match the terrain slopes, timber storefronts, porches, balconies, signs, roof lines and weathered materials. Furnish the saloon, a general store, a storage room and the stable. Include believable street details such as hitching rails, troughs, barrels, stacked goods, fences and wagon tracks, with vegetation and countryside surrounding the town.

## Interactive environment

Provide saloon swing doors, a pair of store doors, a stable gate and two opening drawers. A handcart must be pushable, carry at least three distinct cargo objects, and retain them while turning and traversing the street. Openable crates hold individually transferable goods. Deliver flour, tools and bottles to separate marked storage locations, preserving their identities and counts. The player can open and close the stable gate while standing clear of its motion. Horses may be static; riding, combat and crowd simulation are not required.

## End-to-end activity

Collect the three cargo types in the freight yard, load the cart, travel to the general store, open its doors and unload to the correct storage locations. Return through the stable yard, close its gate and park the empty cart in the freight yard.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
