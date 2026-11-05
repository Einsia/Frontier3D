Design a cheerful static mini-golf park with three parallel lanes on a roughly 25 by 26 metre rectangular site. Each lane should be about 4 m wide and 20 m long, with a marked starting area, continuous green playing surface, low raised side rails and a rounded far end containing a real recessed cup and flag. Keep the playing surface continuous all the way to the cup, without disconnected endpoint tiles or gaps that a ball would fall through. Put a small windmill obstacle on the left lane and a miniature castle arch on the middle lane, each with an opening through which a ball of diameter 0.1 m can pass. Add one low diamond-shaped obstacle near the far end of every lane, with room to pass it on at least one side. Place one ball at each start. Connect all three starts to a common visitor path at least 1.2 m wide, outside the lanes. Use green turf, warm terracotta rails, cream obstacle walls and soft sunny lighting. Choose an elevated oblique camera showing all three courses and their cups. This task produces a scene only; moving windmill blades, scoring and ball physics are not required.

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

Set the `bench_role` custom property on each complete semantic entity or its parent Empty. Group its mesh parts under that parent; annotate distinct entities separately. Role names: ball, castle_arch, cup, diamond_obstacle, lane, site, visitor_path, windmill.
