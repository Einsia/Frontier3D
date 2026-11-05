Build a 19-part camera mount: base, pan sleeve and spindle, fork base, two uprights, camera platform, two tilt pins and bushings, and four bolt-and-washer pairs. The base is 90 × 90 × 8, bottom Z=0, central bore 16.4. A vertical pan sleeve of outside diameter 36, bore 16.4 and height 20 stands from Z=8 to 28. Its diameter-16 spindle is 30 long, centred at Z=21. The fork base is 64 × 50 × 6, centred at Z=31, with a central diameter-16.4 hole; it rests on the sleeve. The two uprights are 6 × 50 × 50, centred at (±28,0,59). Their diameter-14.4 X-axis holes are at Y=0,Z=69. Fit two bushings, outside diameter 14, bore 8.4 and length 6, centred at (±28,0,69). The camera platform is 48 × 64 × 10, centred at (0,0,69), with a diameter-8.4 bore along X. Two diameter-8 pins, each length 16, are centred at (±24,0,69), entering the platform and bushings. Leave the 1 mm lateral gap between platform and each upright. At base positions (X,Y)=(±35,±35), add diameter-6.4 holes and four bolt-and-washer pairs: shanks diameter 6 and length 9.5 from Z=0, washers diameter 12/bore 6.4/thickness 1.5, hex heads height 4 and circumcircle diameter 10.8.

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
