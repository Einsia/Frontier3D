# Embodied Environment: Supermarket and Service Areas

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the photographed supermarket aisles, shelf proportions, merchandise density and materials. Complete the checkouts and service areas consistently with the photographed shop. Connect the shop floor, back stockroom, cold store, loading bay and returns counter. Stock the shelves with varied, recognizable goods and provide realistic back-of-house containers and equipment. Keep cart routes and standing space usable without making the shop feel empty.

## Interactive environment

Provide a working cold-store door, two reusable opening crates, a pushable stock cart and a scanning counter. Use twelve individually transferable stock units from three categories: chilled milk, ambient tins and fragile bottles, four of each. Crates and cart retain their loads. The scanner records each unit once and indicates its category; rescanning does not add another unit. Shelf and cold-store storage use actual supported object positions. Items can be removed and restocked, with count and location remaining consistent.

## End-to-end activity

Receive the twelve units at the loading bay and scan them. Carry milk to the cold store, tins to the ambient shelves and bottles to a separate display shelf. Retrieve one unit of each category to the returns counter, verify the remaining stock and return the cart to the loading bay.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
