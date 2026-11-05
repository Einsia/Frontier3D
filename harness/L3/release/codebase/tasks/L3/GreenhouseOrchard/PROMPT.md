# Embodied Environment: Netted Plant Nursery, Orchard and Irrigation

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the photographed netted nursery, preserving its support poles, shade netting, planting rows, paths and ground materials. Extend it with a coherent orchard and irrigation service area. Connect the growing areas, pump house, reservoir, sorting bench and packing shelter. Include foliage at multiple growth stages, fruit, beds, tools, crates and transport equipment, with credible access for picking and carrying produce.

## Interactive environment

Provide two independently valved irrigation zones and a pump switch. Flow appears only in zones connected to an open valve while the pump runs. Provide twelve pickable fruits, six from each of two visually distinct varieties, and two crates each holding six fruits. Picking removes the specific fruit from its plant; occupied crate positions cannot accept duplicates. A pushable cart carries both crates. A scale reports the actual count and a declared per-item mass for its contents, updating after additions and removals. Implement netted nursery and packing-shelter doors.

## End-to-end activity

Irrigate only the netted nursery zone, then turn the pump off. Pick both varieties, sort them into separate crates, weigh each crate, and deliver both by cart to the packing shelter. Remove one fruit and reweigh to confirm the changed contents.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
