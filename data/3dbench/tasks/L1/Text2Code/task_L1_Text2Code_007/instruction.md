Build a 17-part latch. The mounting plate is 150 × 50 × 5, with bottom Z=0. Put three guide/receiver blocks of size 14 × 26 × 25 on it, centred at X=−45,5,55, Y=0,Z=17.5. Each has a diameter-10.4 X-axis passage at Y=0,Z=20.5. A diameter-10 sliding bolt runs along X, length 118, centred at (5,0,20.5), entering all three blocks. Its vertical handle is diameter 6 and length 24, centred at (−15,0,37.5), touching the bolt at its lower end. Add a cylindrical grip, diameter 14 and height 10, centred at (−15,0,54.5), touching the handle. Two stop rings have outside diameter 16, bore 10.4 and width 4 along X, centred at X=−30 and 25 on the bolt axis. At (X,Y)=(±68,±19), drill diameter-6.4 mounting holes through the plate. Use four diameter-6 bolt shanks 6.5 long starting at Z=0, washers with outside diameter 12, bore 6.4 and thickness 1.5 on the plate, and 4-high hex heads with circumcircle diameter 10.8 on top. Keep the bolt, handle and grip separate even at their touching surfaces.

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
