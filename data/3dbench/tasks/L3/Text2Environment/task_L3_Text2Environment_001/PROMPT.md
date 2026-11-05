# Embodied Environment: Ward and Supply Corridor

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a realistic, unoccupied hospital ward for embodied logistics, occupying approximately 60 by 45 metres on one level. A loop corridor connects six patient rooms, two shared bathrooms, a nursing station, a clean-supply room, a utility room and a cart parking recess. Each patient room contains a bed, bedside cabinet, chair, curtain, handwash point and wall services. Use clean institutional materials, readable room signs, plausible lighting and varied furnishings. Corridors and doorways must accommodate the supplied cart, including turns and passing door leaves.

## Interactive environment

Implement room doors, two locked supply cabinets, six bedside drawers, a movable curtain, a supply cart and one adjustable empty bed. A keycard unlocks the supply cabinets. Stock six towel packs and six empty containers as individually movable objects. The cart carries them without changing identity. The bed's head section and overall height are independently adjustable with attached parts moving consistently. Taps have visible on/off states. Clean supplies and returned containers have separate storage locations. Do not simulate patients, diagnosis or treatment.

## End-to-end activity

Collect the keycard at the nursing station, load six towel packs and deliver one to each bedside drawer. Adjust the empty bed in room 3 and open its curtain. Collect a container from each room, return them to the utility room, then return the card and park the empty cart.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
