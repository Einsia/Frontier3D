Build a nine-part coaxial filter display: housing, filter insert, two caps, two seals, tie rod, round nut and bottom washer. All axes are vertical and centred at X=Y=0. The housing has outside diameter 60, bore 52 and length 70, from Z=8 to 78. At each open end enlarge the bore to diameter 59.4 for a depth of 2.1. The filter insert has outside diameter 42, bore 14 and length 62, centred at Z=43. Each cap is an annulus, outside diameter 68, bore 10.4 and thickness 8; their centres are Z=4 and 82. Each seal is an annulus, outside diameter 59, bore 52.6 and thickness 2, centred at Z=9 and 77 inside the housing end recesses. The tie rod is diameter 10, length 90, centred at Z=43. The top nut is round, outside diameter 18, bore 10.4 and height 5, centred at Z=90. The bottom washer is outside diameter 22, bore 10.4 and thickness 2, centred at Z=−3. Use dark seals, a beige filter and brass-coloured housing and caps. Keep the internal insert in the native scene and visible in the exploded state. This is an unthreaded display assembly, not a pressure-rated filter.

All stated dimensions are in millimetres. Coordinates describe the assembled state; X is length, Y is width and Z is up. Use blue-gray structural bodies, silver shafts and fasteners, and brass sleeves, collars and washers unless a different material is stated. All parts must be closed, individually connected and separately editable. Preserve real holes and specified clearances, with dimensional and placement errors no greater than 0.3 mm. Do not add threads, fillets or hidden machinery that were not requested. Use your own descriptive object names. No input images or models are supplied; do not download a matching assembly.

Export in metres. Save the assembled state at frame 1 and a readable exploded state at frame 61, separating parts without changing their shape. The explosion layout is your choice. Returning to frame 1 must restore the assembly; scene.glb must contain that assembled state. Choose a clear review camera; choose any suitable camera pose and explosion spacing.

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
