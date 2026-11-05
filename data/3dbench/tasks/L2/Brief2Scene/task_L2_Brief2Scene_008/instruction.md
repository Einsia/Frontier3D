Create a stylized sandstone canyon approximately 60 m long and 36 m wide. A dry winding passage, at least 3 m wide, must connect the foreground entrance to an opening at the far end. Flank it with irregular terraced rock masses 8–18 m high, including at least two freestanding pillars, a natural arch with an open span of at least 6 m and scattered broken slabs. Use layered and fractured rock shapes rather than uniformly scaled cubes. Place three separated vegetation clusters with fan palms, branching cacti and low dry grasses on soil pockets, leaving the passage clear. Keep roots grounded and avoid floating rocks or impossible arch support. Use warm orange sandstone, pale dusty ground and restrained green plants, with afternoon side light that separates foreground rocks from the distant ridge. Use metres and Z up. Render a perspective main view from the passage entrance at eye height 1.7 m and a second elevated view at least 8 m above ground showing the route and arch. Render 960 by 640 pixels using Cycles, AgX, exposure 0 and gamma 1. No reference image or starting scene is supplied; the layout is yours to design.

Keep both cameras in the native scene, keep major structures independently editable and pack dependencies.

Use only supplied inputs to establish this scene. Do not retrieve the original complete model or additional views online. Do not replace three-dimensional structures with the entire reference projected onto planes.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: far_exit, foreground_entry, natural_arch, passage, pillar, rock_mass, site, vegetation_cluster.
