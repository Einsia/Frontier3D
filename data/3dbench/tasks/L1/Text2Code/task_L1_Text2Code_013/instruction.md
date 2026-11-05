Create one closed, connected machined sleeve from text only. All dimensions are millimetres. Its axis is vertical Z, outside diameter 36.21, overall height 80.6 and through-bore diameter 15.9. Put its bottom at Z=0. Cut a square-section circumferential groove into the outside, width 6.06 along Z and radial depth 2.21, centred at Z=50.8. Keep the groove shoulders sharp. On both end faces apply 0.9 × 0.9 mm, 45-degree chamfers to both the outer and bore edges. Do not chamfer the groove. Use a blue-gray metallic material. Preserve the bore as a real through-opening and the remaining continuous wall. The dimensions describe the actual surfaces, not an approximate bounding box.

Export in metres with Z up. Dimensional and surface-position error must stay within 0.15 mm. Keep one editable part; no assembly or exploded state is required. No reference image, model or structured specification file is supplied. Do not download the source model.

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
