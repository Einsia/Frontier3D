# Cheung Chau Ferry Terminal and Market Service Area

Use the supplied reference views as the visual target. Preserve their visible spatial relationships, proportions, materials and atmosphere; complete unseen areas consistently. Build the connected environment described below, with coherent surrounding scenery.

Recreate the photographed Cheung Chau ferry terminal, shoreline, quay levels, canopies and surrounding waterfront character. Complete the waiting hall and add a coherent adjacent market, service lane and warehouse. Connect the waiting area to a fixed docked ferry through a gangway, and connect market deliveries to the warehouse without blocking passenger access. Include seating, signs, bollards, railings, ropes, stacked crates and weathered coastal materials. Complete the waiting hall, several market stalls and warehouse interior.

## Interactive environment

Implement two boarding gates, an adjustable gangway, three stall shutters, two retractable awnings and a delivery cart. The gangway has stowed and deployed states; boarding gates open only after deployment and close before retraction. The deployed surface and railings allow the player to reach the stationary ferry. Shutters and awnings physically clear the stall goods. Six cargo units can be transferred from the warehouse to three distinct stalls, two per stall. The ferry remains fixed; navigation and tide simulation are not required.

## End-to-end activity

Load six units at the warehouse, open the stalls and deploy their awnings, then deliver two units to each stall. Deploy the gangway, open boarding access and walk onto the stationary ferry and back. Close boarding access, stow the gangway and return the empty cart.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
