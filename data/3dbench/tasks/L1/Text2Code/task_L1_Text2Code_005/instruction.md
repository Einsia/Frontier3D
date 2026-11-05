Build a 16-part pulley support: base, two fork cheeks, a grooved pulley, bushing, axle, two collars and four bolt-and-washer pairs. The base is 80 × 70 × 8 with bottom Z=0. Each fork cheek is 8 × 42 × 64, centred at X=±20, Y=0, Z=40. Its diameter-10.4 bore runs along X at Z=50. The pulley axis is X at Y=0,Z=50. Its centre barrel is diameter 40 and length 18, centred at X=0. Add two diameter-50 rims, each 3 thick, centred at X=±10.5; fuse the barrel and rims into one part. Its through-bore is diameter 16.4. Fit a bushing, outside diameter 16, bore 10.4 and length 24, centred inside the pulley. The axle is diameter 10, length 58, centred at X=0. The two collars have outside diameter 18, bore 10.4 and width 3, centred at X=±28. The wheel has 4 mm clearance to each fork cheek. At (X,Y)=(±30,±24), drill diameter-6.4 holes through the base. Add four diameter-6 bolt shanks of length 9.5 from Z=0, diameter-12/6.4 washers 1.5 thick on the base, and hex heads 4 high with circumcircle diameter 10.8 on those washers.

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
