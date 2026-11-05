Design a cheerful low-poly island harbour, viewed from an elevated three-quarter angle. Use a roughly 34 by 32 metre site, with open blue water on the left and a sandy quay on the right. A timber pier must reach the shore and branch into a docking finger, with visible piles supporting it above the water. Keep a continuous walking route at least 1.2 m wide from the shore to the docking end. Place one substantial two-masted sailing ship beside the pier, and a smaller rowing boat nearby. The ship needs a shaped hull, deck, raised stern cabin, railings, masts, curved sails and supporting rigging; a box with sail triangles is insufficient. Its hull must sit partly below the water while its accessible deck is above it. On land, include a raised open-sided hut with four supports and a pitched or hipped roof, a separate small stone lookout tower with crenellations, at least four bent palms, and at least five barrels and five crates grouped as a loading area. Arrange the loading area without blocking the pier connection. Use warm timber, cream sails, sandy ground and turquoise water, with clear soft daylight and readable silhouettes. Keep the full ship, shoreline and pier visible in the primary view. This is an editable static scene; no sailing simulation or characters are needed.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: barrel, crate, docking_end, hut_support, mast, palm, pier, rowing_boat, ship_deck, ship_hull, shore, site, water.
