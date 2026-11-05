Create one closed, connected curved bar from text only. Use millimetres in the following construction. Its centreline lies in the XZ plane and interpolates these ordered (X,Y,Z) points: (0,0,0), (0,0,10.348767), (11.4975,0,20.995524), (15.5835,0,21.221145), (16.821,0,42.57). Use a non-periodic C2 interpolating B-spline, with chord-length parameters and no user-specified endpoint tangents; OpenCascade GeomAPI_Interpolate at tolerance 0.000001 mm defines the reference interpolation. Sweep a centred 9.3 × 6.9 rectangular section, initially in the XY plane at the origin (9.3 along X, 6.9 along Y), along that path using corrected-Frenet transport and no extra twist. Keep the section depth parallel to Y. Close both end faces; retain the four longitudinal edges without fillets. Use a blue-gray metallic material. Do not approximate the shape by a chain of separate rectangular blocks. The closely spaced middle interpolation points are deliberate and create the change of bend.

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
