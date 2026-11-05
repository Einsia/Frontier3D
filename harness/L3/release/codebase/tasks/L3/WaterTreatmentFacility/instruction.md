# Embodied Environment: Water Treatment and Maintenance

Create this environment from the written brief. Design the layout and architectural details yourself while satisfying the specified spaces, style and functions.

Create a realistic small water-treatment facility of approximately 180 by 130 metres. Include a raw-water tank, two parallel treatment lines, a clean-water tank, pump house, control room, parts store and elevated inspection platforms. Show understandable pipe connections, bends, supports, gauges and access points. Connect buildings and platforms with ground paths and stairs, with railings around tanks and elevated edges. Use weathered concrete, painted steel, pipes, wet surfaces and functional industrial lighting.

## Interactive environment

Each treatment line has an inlet valve, outlet valve and removable filter inside an opening maintenance housing. A pump switch supplies the system. Isolate both valves on a line and stop the pump before releasing that filter; otherwise opening the housing or removing it is refused. Provide one spare filter and a cart. Reinsert and latch a filter before restoring that line. Visible flow and tank inflow depend on pump state, valve connectivity and installed filters; the second line remains independently configured. Use a deterministic process model rather than chemical or full fluid simulation. These interlocks are a simplified task specification.

## End-to-end activity

Inspect the marked first line, stop the pump and isolate that line. Fetch the spare filter, replace the installed filter and carry the used one to the parts store's return bin. Close the housing, reopen the line and restart the pump; show restored inflow without changing the second line's valve settings.

Make this a detailed, visually coherent environment with sensible layout, accessible routes, stable object placement and clear interaction feedback. Inspect both appearance and behaviour during development. Follow the supplied L3 generation and delivery contract.
