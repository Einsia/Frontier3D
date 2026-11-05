Create a three-dimensional assembly of a two-hub shaft coupling from scratch. Arrange two flanged coupling halves coaxially, each holding a separate shaft, and connect them with three bolts. Include three washers and one central spacer ring, for 11 separate parts in total. All dimensions and assembly requirements are given below; no reference image is provided.

All dimensions are in mm. The two coupling halves are identical: each flange is outer diameter 54 and thickness 8, with a central hub of outer diameter 24 and overall length 18, centered on the flange's mid-plane. The central through-bore is diameter 16.4. Each flange has three through-holes of diameter 6.4 on a diameter 40 pitch circle, equally spaced by 120°. Each shaft is diameter 16 and length 24. The central spacer ring is outer diameter 28, inner diameter 16.8 and thickness 3. Each of the three washers is outer diameter 12, inner diameter 6.4 and thickness 1.5. Each of the three bolts has a shank of diameter 6 and length 31.5, with a hexagonal head of height 4 and circumcircle diameter 10.8.

Stand the coupling vertically, with the flange mid-planes 22 apart and their three bolt holes aligned. Insert one shaft inward from each outer end of the assembly. Each shaft center lies 21 outward from its corresponding flange mid-plane. Center the spacer ring between the coupling halves. Place each washer on the upper flange's top face, with the bolt head above it and the shank passing through the matching holes in both flanges. Keep the two shafts separate and preserve the axial gap between the coupling halves. Use blue-gray for the flanges, silver-gray for shafts and bolts, and brass tones for washers and spacer.

Keep each part separate, closed and connected within a clear assembly hierarchy. Dimensional and assembly-position errors must each remain within 0.3 mm. Export in metres with Z up; choose your own origin. Show the assembled state at frame 1 and a legible exploded state at frame 61. Choose separation directions and distances yourself while preserving part shapes and allowing restoration of the assembly. Submit the fixed `output/` files required by the submission contract.

## Submission contract
Place every deliverable under `output/` in the task workspace. The evaluator will read these exact paths:

```text
output/
  solution.py       # reproducible Blender generation or editing entry point
  scene.blend       # editable native scene
  scene.glb         # assembled/exported result
  README.md         # short dependency and execution note
  assets/           # optional local textures or other files needed at runtime
```

Run the entry point from a clean copy with Blender in background mode:
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`
The script must resolve helper files relative to itself, read task data only from the supplied `input/` files and its own `output/assets/` (bundled helper code and installed libraries are allowed), and write or refresh the required outputs in `output/`. The supplied initial `.blend`, when present, is allowed. Do not rely on previously generated output files or hard-coded personal paths; pack textures into the saved scene or use portable relative paths under `output/assets/`. Keep the required output filenames exactly as shown; optional renders or logs go under `output/renders/` or `output/logs/`.
