# Embodied Environment: Repair Workshop and Loading Yard

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the photographed workshop, matching the work bays, machinery, storage and material wear. Add a connected outdoor loading yard with a compatible industrial character. Connect the parts store, two distinct workstations, packing area and outdoor pallet zone. Include credible tool racks, benches, cabinets, fixtures, cables, containers and partially assembled items. Place the equipment so that parts can be carried and a pallet truck can travel through the loading door.

## Interactive environment

Implement two sliding drawers, a lockable tool cabinet, a bench vice, a height-adjustable worktable, a loading door and a pallet truck. Supply a base, bracket, two fasteners and an appropriate tool as distinct movable items. The vice holds the base; the bracket can be fitted and secured only with the base clamped and the tool available. Releasing the vice allows the assembled unit to be removed as one object. The worktable retains its load while moving. The pallet truck engages, raises, transports and lowers a pallet carrying the packed unit.

## End-to-end activity

Unlock the tool cabinet, collect the parts, clamp the base, fit and fasten the bracket, release and inspect the unit, pack it, then move the pallet through the loading door to the marked outdoor bay. Return the tool and park the pallet truck with its forks lowered.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
