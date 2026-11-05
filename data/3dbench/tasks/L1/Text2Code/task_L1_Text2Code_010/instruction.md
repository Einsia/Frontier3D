Build a nine-part telescopic tube: outer and inner square tubes, two square guide rings, bottom plug, top cap, transverse pin and two pin retainers. The outer tube has a 44 × 44 exterior and 36 × 36 opening, length 80, from Z=0 to 80. The inner tube has a 32 × 32 exterior and 26 × 26 opening, length 90, from Z=40 to 130. Both share the vertical axis. The guide rings have a 35.6 × 35.6 exterior, 32.4 × 32.4 opening and height 8, centred at Z=8 and 70. The lower ring is an empty guide below the current inner-tube end. The bottom plug is a 43 × 43 × 5 plate centred at Z=−2.5; the top cap is 34 × 34 × 4 centred at Z=132. A diameter-6 locking pin, length 58, runs along X at Y=0,Z=66. Cut diameter-6.4 aligned X-axis holes through both tubes; also cut the intersecting lower edge of the upper guide ring so the pin clears it. The two pin retainers are outside diameter 12, bore 6.4 and width 2 along X, centred at X=±30 on the pin axis. Keep the square-tube clearances and the separate brass-coloured guides.

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
