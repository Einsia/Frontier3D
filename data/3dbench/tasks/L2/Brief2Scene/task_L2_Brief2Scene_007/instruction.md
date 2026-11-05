Build a calm low-poly coastal lighthouse scene. A white lighthouse with a broad red horizontal band should stand on a small irregular rocky island surrounded by blue water. Make the tower about 30 m tall, tapering gently upward, with a separate dark roof, a band of recessed lantern-room windows, and a projecting ledge or gallery below that room. The tower must sit on the island rather than float above it. Give the island a green upper surface and faceted exposed rock sides; its main footprint should be roughly 35–50 m across. Place six to ten three-dimensional conifers beside the lighthouse at varied heights, with visible trunks and layered foliage. They must not obscure the lantern or be represented only by camera-facing billboards. Use readable broad colour areas and a directional daylight shadow over the sea. Frame the entire lighthouse and island with some surrounding water in an elevated three-quarter view. No nearby town, boats, animated waves or beacon mechanism is required.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: island, tower, tree.
