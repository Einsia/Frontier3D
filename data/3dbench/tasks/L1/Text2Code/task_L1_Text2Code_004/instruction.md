Build a 10-part vise: base, two jaw blocks, two liners, two guide rods, a smooth drive rod, a handle hub and a crossbar. Use a 160 × 90 × 10 base with bottom Z=0. Jaw blocks are 18 × 76 × 50, centred at (−60,0,35) and (20,0,35). Their opposing liners are 3 × 76 × 20, centred at (−49.5,0,50) and (9.5,0,50), touching the jaw faces. The two guide rods run along X at Y=±25, Z=27: diameter 8, length 130, centred at X=0. The drive rod runs along X at Y=0, Z=27: diameter 10, length 150. Both blocks have matching X-axis through-bores of diameter 8.4 for the guides and 10.4 for the drive rod. The handle hub is centred at (81,0,27), normal to X, with outside diameter 20, bore 10.4 and length 12. Its inner face meets the end of the drive rod. Drill a diameter-6.4 transverse Y-axis passage through the hub. A diameter-6, length-70 crossbar runs through that passage, centred at (81,0,27). This is an unthreaded static assembly; do not add a hidden screw mechanism.

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
