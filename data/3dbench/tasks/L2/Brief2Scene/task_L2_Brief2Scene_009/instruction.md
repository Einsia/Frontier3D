Create a realistic barren lunar surface composition, viewed from a low camera roughly 1.6 m above the local ground. Include a gently undulating foreground of gray regolith, at least three shallow craters with raised irregular rims, scattered small stones and several larger angular rocks, and low distant ridges forming a layered horizon. Build the foreground and midground as genuine terrain geometry, not an image plane or a flat floor covered only by a normal map. Let rock sizes range approximately from 0.05 m pebbles to 1 m boulders, with partial burial and varied orientations. Use fine regolith detail without repeating an obvious tiling pattern across the image. Light the scene with a single dominant low-angle sun so that rocks and crater rims cast long coherent shadows against a nearly black sky. Place a small partially illuminated blue Earth above the distant horizon; keep it clearly separate from the terrain and much smaller in the image than the foreground landforms. Use an exposed terrain area of at least 80 by 80 metres so a second camera 2 m to the side reveals consistent nearby parallax. No astronaut, lander, labels, camera crosshairs, animation or orbital calculation is needed.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: crater, rock, site.
