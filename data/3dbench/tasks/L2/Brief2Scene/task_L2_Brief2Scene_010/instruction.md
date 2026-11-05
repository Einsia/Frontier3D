Create from scratch a cartoon construction site suitable for a top-down management game. Use a site approximately 40 m × 30 m containing an unfinished building, a tower crane, a concrete mixer truck, a dump truck, material storage, temporary roads, and a perimeter fence with a gate. Connect the entrance to the work zone with a road providing at least 4 m of clear width. Keep materials off the road and give vehicles and equipment plausible ground contact and support. Use low-poly forms, simple color blocks and consistent proportions so that work, transport and storage areas are immediately readable. Use an orthographic main camera at approximately 60° elevation and render at 1280×960; choose another azimuth to show the same scene. No reference image or initial model is provided; design the building forms, palette and layout yourself. Submit the fixed `output/` files required by the submission contract and retain both final cameras in the native scene. Use metres, Z up, and seed 20260914.

## Submission contract
Place every deliverable under `output/` in the task workspace. The evaluator will read these exact paths:

```text
output/
  solution.py       # reproducible Blender generation or editing entry point
  scene.blend       # editable native scene
  main.png          # required primary view
  alternate.png     # required second view
  README.md         # short dependency and execution note
  assets/           # optional local textures or other files needed at runtime
```

Run the entry point from a clean copy with Blender in background mode:
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`
The script must resolve helper files relative to itself, read task data only from the supplied `input/` files and its own `output/assets/` (bundled helper code and installed libraries are allowed), and write or refresh `scene.blend`, `main.png` and `alternate.png` in `output/`. Do not depend on an earlier submission, an absolute personal path, or files outside the task workspace. Both images must come from the same saved scene and use the cameras/settings required above. Keep the required output filenames exactly as shown; optional renders or logs go under `output/renders/` or `output/logs/`.

## Materials

Use solid colors or procedural materials only. Reference images are for observation. Do not use bitmap textures, HDRIs, baked/generated images, or image-driven shaders, lights, geometry nodes or compositing. Procedural Noise and Bump nodes are allowed.

## Scene object annotations

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: dump_truck, entrance, mixer_truck, road, site, work_zone.
