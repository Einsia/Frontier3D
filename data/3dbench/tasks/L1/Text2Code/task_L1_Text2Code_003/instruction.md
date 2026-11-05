Build an 11-part positioning stage with a base, two guide rods and sleeves, a smooth lead rod, a nut block, a moving platform, two end supports and a handwheel. The base is 170 × 100 × 6, centred in plan with its bottom at Z=0. Two diameter-8 guide rods run along X, length 150, at Y=±30 and Z=26. Each carries a centred sleeve of length 40, outside diameter 18 and bore 8.4. A central diameter-10 lead rod runs along X at Y=0, Z=26, length 182. Its nut block is 24 × 22 × 18, centred at (0,0,26), with a diameter-10.4 X-axis bore. The platform is 58 × 86 × 6, centred at (0,0,38); its underside touches the nut block and guide sleeves. End supports are 12 × 90 × 36, centred at (−76,0,24) and (76,0,24), standing on the base. Their three X-axis passages at Z=26 have diameters 8.4, 10.4 and 8.4 at Y=−30,0,+30. Centre the handwheel at (88,0,26), normal to X: outside diameter 36, bore 10.4 and width 6. The extended lead rod reaches the outer face of the wheel. No helical threads are needed.

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
