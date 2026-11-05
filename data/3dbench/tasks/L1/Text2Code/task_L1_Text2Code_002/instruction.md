Build a 16-part horizontal shaft support: a base, two upright bearing blocks, two plain bearing sleeves, two shaft collars, one shaft and four bolt-and-washer pairs. Use a 140 × 70 × 6 base, with its bottom at Z=0 and its plan centre at X=Y=0. The shaft runs along X at Y=0, Z=34. The two blocks are 18 × 48 × 42, centred at X=−42 and +42, with their bottoms on the base. Each has a diameter-24.4 transverse bore centred on the shaft axis. Fit an 18-long sleeve, outside diameter 24 and inside diameter 16.4, flush within each block. The shaft is diameter 16, length 130, centred at X=0. Put a collar, outside diameter 24, bore 16.4 and width 5, at X=−56 and +56. Each block has two vertical diameter-6.4 mounting passages at Y=−18 and +18, continuing through the base. At these four positions use diameter-6 bolt shanks 49.5 long, starting at Z=0; washers of outside diameter 12, bore 6.4 and thickness 1.5 rest on the blocks at Z=48; hex heads are 4 high with circumcircle diameter 10.8 and rest on the washers.

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
