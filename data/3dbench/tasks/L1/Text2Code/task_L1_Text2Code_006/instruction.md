Build a 14-part indexing table: base, sleeve, spindle, disk, indexing pin, top retaining ring and four bolt-and-washer pairs. Use a 100 × 100 × 8 base, bottom Z=0, with a central diameter-16.4 through-hole. On its centre put a sleeve of outside diameter 28, bore 16.4 and height 11, from Z=8 to 19. A diameter-16 spindle is 26 long, centred at Z=17. The disk has outside diameter 84 and thickness 8, centred at Z=23, resting on the sleeve. Its centre bore is 16.4. Six diameter-6.4 through-holes lie on a diameter-64 pitch circle at 60-degree intervals, starting at positive X. A diameter-6 indexing pin is 18 long, centred at (32,0,22), through that first hole. A separate retaining ring, outside diameter 26, bore 16.4 and thickness 3, is centred at Z=30. At (X,Y)=(±40,±40), add diameter-6.4 base holes, diameter-6 bolt shanks 9.5 long from Z=0, washers of outside diameter 12/bore 6.4/thickness 1.5 on the base, and 4-high hex heads with circumcircle diameter 10.8. Preserve the stated axial clearances; this is a static layout rather than a load-tested locking mechanism.

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
