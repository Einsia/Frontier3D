Design a compact stylized planetary surface outpost on a roughly 36 by 32 metre dusty site. The primary view should be elevated and show the whole facility. Organize a large vehicle hangar, a separate glazed dome, a power generator and a steerable-looking communications dish around a shared work apron. Model the hangar entrance with depth and enough clearance for the parked rovers. Put three small wheeled rovers on the apron, leaving a connected route at least 2 m wide between the hangar entrance and the open edge of the apron. Add one upright rocket with a distinct engine/base section, two stacked tank sections and a nose section; these sections should connect without floating gaps. Along the opposite side, build a straight elevated test rail 18–22 m long, about 2.5–3 m above the ground, on at least six supports, carrying one short rail vehicle. Give its track and wheels or guide system a plausible spatial relationship. Rail supports must not block the rover route. Include exposed pipes near the power unit and at least four shallow terrain craters placed outside the apron. Use chunky white and muted orange equipment, dark windows, dusty ground and soft daylight. Major structures must have actual volume, entrances and attachments. This is a static environment; no vehicle movement or orbital physics is required.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: apron, apron_edge, crater, hangar_entry, rail, rail_support, rail_vehicle, rocket, rover, site, tank_section.
