Build a compact cartoon suburban street diorama on a roughly 32 by 34 metre site. Run a straight 6 m wide two-way road through the centre, with dashed centre markings and continuous sidewalks at least 1.2 m wide on both sides. Arrange six detached houses, three per side. Each house must face the road and have a distinct combination of footprint, roof shape, facade colour and window arrangement; merely recolouring one repeated box is not sufficient. Include visible front doors, recessed or framed windows, roof overhangs and at least two houses with chimneys. Connect each property to its sidewalk with a short driveway or entry path. Keep the road and the full width of the sidewalks clear of buildings, trees and planters. Provide at least twelve trees distributed in the gardens and six planters near the houses; keep front entrances readable. Use modest low-rise proportions, pastel plaster, contrasting roof colours, simple foliage volumes and sunny soft shadows. Choose an elevated oblique view that shows all six houses and the road connection at both ends. No traffic, pedestrians or building interiors are required.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: chimney, house, planter, property_entry, road, sidewalk_left, sidewalk_right, site, tree.
