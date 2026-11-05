# Overwatch: Rialto Canal Plazas and Service District

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the Overwatch Rialto canal-side district in the reference images as a polished, stylized environment. Connect the canal plaza, shopping street, side alleys, warehouse and elevated walkway. Match the references' architecture, colours, clean material separation, readable silhouettes and scenic background. Complete the main street route and an alternative elevated route, and furnish the warehouse, a small shop and a maintenance room. The environment should read as a complete game location at both street level and from an overview.

## Interactive environment

Make the maintenance panel control district service power. Power enables two warehouse shutters and a two-stop freight lift; loss of power stops motion in place, and restoring power allows explicit continuation. Lift doors remain closed between landings. A movable cargo platform follows the street route, stops at a closed barrier or obstacle and can resume when clear. It must carry actual crates. A dock latch secures the delivered platform. Implement these as task-specific logistics interactions; weapon systems and multiplayer gameplay are outside scope.

## End-to-end activity

Restore service power in the maintenance room, open the warehouse, use the lift to retrieve two upper-storey crates, load the street platform, clear the route and deliver to the dock. Secure the platform, unload the crates and verify their new locations.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
