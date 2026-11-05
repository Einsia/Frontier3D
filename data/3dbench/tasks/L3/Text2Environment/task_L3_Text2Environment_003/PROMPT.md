# Outer Wilds-inspired Hydraulic Alien Ruins

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create an Outer Wilds-inspired alien hydraulic ruin: an approximately 240 by 180 metre valley complex with an upper reservoir, a central ring-shaped courtyard, two lower water basins, underground channels, a control chamber and an observation terrace. Connect the terraces with stairs, walkways and eroded stone passages. Use ancient pale stone, patterned metal mechanisms, luminous symbols, weathering and vegetation to make the water system's purpose legible. Furnish the control chamber, a maintenance chamber and a small archive with coherent instruments and artefacts. The ruin should feel embedded in a larger landscape.

## Interactive environment

Use two independently controlled basins, each with a visible low and high water level. An inlet valve and drain gate govern each basin; filling requires an open inlet and closed drain. A floating platform follows basin A's level and carries the player to an upper walkway. Basin B's low level exposes a dry lower passage, while its high level makes a second floating crossing usable. Include a power switch for the inlet pump, animated valve wheels and moving sluice gates. Water levels change gradually with visible flow cues; deterministic animation is sufficient, with no requirement for fluid simulation or underwater locomotion.

## End-to-end activity

Begin with both basins low and the pump off. Reach the control chamber through the lower route, enable the pump, fill basin A and ride the platform upward. Fill basin B to cross to the observation terrace, open its drain from the far side, then return through the exposed lower passage. Revisit basin A and preserve its independently set level.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.

## Workspace and delivery

Work in /workspace/project. Read input/CONTRACT.md, input/INTEGRATION.md, input/interaction-contract.json, input/ASSETS.md and input/REFERENCES.md. The compiled starter is a generic lighting/material equipment fixture; replace its test geometry. L3DefaultEnvironment.h provides a usable sky and daylight setup, which you may keep or replace.

Build: `python3 /opt/l3-public/ue.py build /workspace/project --output /workspace/checks/build-001 --jobs 16`

Preview: `python3 /opt/l3-public/ue.py preview /workspace/project --output /workspace/checks/view-001 --position X Y Z --target X Y Z`

Use fresh output directories. Inspect the references and your actual multi-view PNGs with image tools; autonomously edit, compile, run and improve the project. Test the continuous activity and the key mechanisms. Aim to finish within one hour of active generation, but finish and validate the deliverables rather than stopping an unfinished scene at a fixed deadline. Generation wall time, model calls, tokens, tools and retries are recorded. Network access is disabled except for the authorized model service. End with the complete editable project, bindings, asset provenance, controls and genuine final previews.
