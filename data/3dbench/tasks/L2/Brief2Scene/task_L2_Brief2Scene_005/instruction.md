Create a small stylized cemetery garden on a 24 by 24 metre site. A straight path at least 2 m wide should lead from an opening in the front fence to a small roofed crypt at the rear. Arrange twelve graves in three rows on either side of this path, six graves per side. Give every grave a distinct grave bed and upright marker; use rounded markers on one side and cross-shaped markers on the other. Keep every marker clear of the walking path. Enclose the remaining perimeter with a thin iron fence and visible posts, leaving the front entrance open. The crypt needs a door recess, separate roof and a readable facade. Add four crooked conifers near the corners and three light posts along one side of the path. Use dark muted soil, pale stone, subdued green foliage and a calm overcast daylight look. Choose an elevated view that makes the rows, central route and crypt easy to read. Do not include people, inscriptions, horror effects or animation.

No reference image or source model is supplied. Create the scene from this brief using Blender, metres and Z up. Keep major structures separately editable, pack all texture dependencies, and use one consistent scene for both views. Unless a different alternate view is specified above, orbit the primary camera 25 degrees around the site centre at the same height and distance and aim at the same point. Render both images at 1200 by 1000 pixels with Cycles, AgX, exposure 0 and gamma 1. Use a fixed random seed for any procedural variation and state it in README.md. Do not download or retrieve a prebuilt scene as your answer.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: crypt_entry, entrance, grave, light_post, path, site, tree.
