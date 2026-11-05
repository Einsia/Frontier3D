Build a 15-part serviceable electronics box: body, gasket, lid, four standoffs, four screws and four washers. The body has outside dimensions 100 × 70 × 35, bottom at Z=0; its centred rectangular cavity is 92 × 62 and opens upward, with a 4.5 mm floor. Its vertical walls are 4 mm thick. The rectangular gasket follows the body rim, outside 100 × 70, opening 92 × 62 and thickness 2, occupying Z=35 to 37. The lid is 100 × 70 × 4, occupying Z=37 to 41. At (X,Y)=(±40,±25), both the lid and body floor have diameter-4.4 through-holes. Four tubular standoffs stand on the inner floor at those locations: outside diameter 9, bore 4.4, length 32.5, spanning Z=4.5 to 37. Each screw has a diameter-4 shank of length 13.5 from Z=29 to 42.5 and a 4-high hex head with circumcircle diameter 7.2. A washer of outside diameter 8, bore 4.4 and thickness 1.5 lies under each head on top of the lid. Use a dark gasket and metallic standoffs. Do not model threads. The lid, gasket and standoffs remain independently editable.

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
