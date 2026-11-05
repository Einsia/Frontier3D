Design a colourful low-poly castle on a roughly 29 by 28 metre grassy base. Enclose a courtyard roughly 18 m square with thick crenellated walls and four taller corner towers. The wall runs must meet the towers without open corner gaps. At the centre of the front wall, build an open gateway at least 2 m wide and 2.5 m high, with a visibly lowered timber drawbridge leading into it. A visitor must have an unobstructed route from the bridge, through the gateway, into the courtyard; do not fill the opening with a wall or closed gate. Place a taller roofed keep toward the rear of the courtyard, a stone stair, one small wooden catapult and a tree to one side, preserving a clear central area. Walls and towers need visible thickness, battlements, projecting ledges and readable openings; roofs should have a distinct silhouette and overhang. Use warm gray stone, dark red roofs, timber details and green ground. Show the gate, inner courtyard and keep in an elevated three-quarter composition. No combat systems, rigging or playable navigation are required, but the geometrical path must be clear.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: bridge_start, corner_tower, courtyard, courtyard_goal, entry_route, gateway, site.
