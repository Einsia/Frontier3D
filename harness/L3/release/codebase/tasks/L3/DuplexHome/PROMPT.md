# Embodied Environment: Furnished Kitchen and Utility Suite

Recreate the furnished kitchen and dining corner in the supplied photographs, matching the cabinets, worktops, refrigerator, appliances, blinds, table, small household objects and warm light. The four views come from one real room. Make the room fully explorable and complete a compact connected utility room, entrance hall and garden-tool store consistently with it. These adjoining spaces are a design extension, not additional photographed rooms. Give cupboards, drawers and appliances usable interiors and working clearances. Keep the density and character of the photographed kitchen while allowing a person carrying a basket to move through it.

## Interactive environment

Implement two room doors, two drawers, two cupboard doors, a refrigerator door and a washing-machine door. Supply two garments, a plate, a cup, a detergent bottle, a garden tool and a transport basket as distinct movable objects. The basket retains its contents while carried or placed. A kitchen tap visibly turns water on and off. The washer starts only with both garments loaded, one detergent dose added and its door closed. Its short cycle locks the door until finished, then allows unloading. Adding detergent consumes one of the bottle's three doses without destroying the bottle.

## End-to-end activity

Take the basket from the utility room, collect both garments from the utility shelf, load and run the washer, put the plate and cup into kitchen storage, and carry the garden tool to its store. Return to unload the finished laundry into the basket. Keep all item identities and resulting states consistent.

Create a detailed, coherent environment with sensible layout, stable placement and clear visual interaction feedback. Inspect appearance and behaviour during development and follow the supplied delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
