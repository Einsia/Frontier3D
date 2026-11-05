Create an editable vertical bolted-flange assembly from the following dimensions. It consists of two identical circular flanges, one through shaft, four hex-head bolts and four washers: 11 separate solid parts. No reference image or initial model is supplied.

All dimensions below are in millimetres. Each flange has outer diameter 90, thickness 12 and a central through-bore of diameter 20.4. Add four through-holes of diameter 6.4 at equal 90-degree intervals on a 64-diameter pitch circle. The shaft has diameter 20 and length 46. Each bolt has a diameter-6 cylindrical shank 27.5 long and a hexagonal head 4 high with circumcircle diameter 10.8. Each washer has outer diameter 12, inner diameter 6.4 and thickness 1.5. Threads and edge chamfers are not required.

Use the lower flange's bottom face as height zero. Place the upper flange's bottom face at height 14, leaving a 2 mm gap between the flange faces. Center both flanges on the same vertical axis and align their four bolt holes. Place the shaft center at height 20. Seat each washer on the upper flange, with its bottom at height 26. Each bolt enters from above, its head resting on its washer and its shank extending down through the aligned flange holes to height zero. Keep the shaft, flanges, bolts and washers as independently editable parts. Use blue-gray flange bodies, silver-gray shaft and bolts, and brass-colored washers.

Use metres and Z up in the exported files. Keep dimensional and assembled-position errors within 0.3 mm. Every part should be closed and connected, with real through-holes and no unwanted solid intersections; small specified shaft and bolt clearances must remain. Show the assembled state at frame 1 and a legible exploded state at frame 61. Choose the explosion directions and distances yourself, preserving each part's shape and allowing the original assembly to be restored. The GLB must represent frame 1. Choose your own descriptive names and a clear assembly hierarchy.

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
