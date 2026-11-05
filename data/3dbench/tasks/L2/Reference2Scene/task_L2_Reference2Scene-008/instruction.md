Reconstruct the antique shop in input/reference.png. Build the timber floor and beams, brick columns and archway, tall open display shelving, rear cabinetry, wall pictures and clocks, rugs, barrels and boxes, lamps, pots, vessels and busts. Preserve the foreground shelving occlusion, central route through the arch and the deeper adjoining room. Shelves need open gaps and real thickness; arches need curved openings and masonry depth. Use varied genuine three-dimensional objects to recover the dense but grouped display, rather than flat textures of clutter. Match warm light, worn timber and the contrast between the bright rear room and darker foreground. Set the arch opening height to 2.4 m as a scale convention. Small labels and picture subjects may be simplified.

Use metres and Z up. The stated size is a task convention, not a measurement of the author scene. Keep main objects independently editable and pack texture dependencies. Complete unseen areas plausibly; exact source object names, hidden dimensions and topology are not required. Match the supplied composition with a perspective main camera. Duplicate it and translate it 0.30 m along local positive X, retaining projection, lens/orthographic scale and rotation, to make an alternate camera. Keep both cameras and render both views from the same scene at 800 by 450 pixels with Cycles, Filmic, exposure 0, gamma 1. The alternate view has no target image and checks 3D consistency.

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

Set `bench_role="scale_anchor"` for the arch surround bounding the central route. Tag the left/right sides and lintel or arch as one entity using a tagged parent, or tag a single joined surround mesh. Tag the threshold/floor below as scale_support.  Door leaves are excluded from the surround and may be closed; the arch route must remain open.
