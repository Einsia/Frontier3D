Build a 14-part four-roller guide: base, central square workpiece, four rollers, four pins and four spacers. Use a 120 × 120 × 8 base with bottom Z=0. The workpiece is 30 × 30 × 50, centred at (0,0,33), standing on the base. Four vertical roller axes are at (X,Y)=(−28,0),(28,0),(0,−28),(0,28). Each roller is an annulus of outside diameter 25, bore 8.4 and height 28, centred at Z=35. This leaves 0.5 mm between each roller and the workpiece. Each pin is diameter 8 and length 46, from Z=6 to 52. In the base, cut a matching diameter-8.4 blind recess from its top down to Z=5 at each axis. Each spacer has outside diameter 14, bore 8.4 and height 13, from Z=8 to 21, supporting its roller. Use a blue-gray base, silver pins and brass rollers, workpiece and spacers. All rollers must remain independent and coaxial with their own pins. Do not replace their bores by painted circles.

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
