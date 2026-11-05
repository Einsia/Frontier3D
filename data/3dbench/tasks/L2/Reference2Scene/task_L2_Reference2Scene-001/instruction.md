Reconstruct the classroom in input/reference.png. Build the rows of individual desks and chairs, the broad front chalkboard and its timber surround, wall notices and clock, ceiling lights and conduits, the windows and radiator, and the smaller classroom objects visible between the furniture. Preserve the staggered perspective of the desk rows and the open walking spaces. Desks need tabletops, storage or lower frames where visible, and separate legs; chairs need shaped seats, backs and supporting frames. Model the chalkboard ledge, window recesses and raised wall trim. Match the warm, worn materials and the strong daylight across the floor and furniture. Chalk markings and paper contents may be simplified; the placement and proportions of these surfaces still matter.

Set the foreground desk tabletop height to 0.75 m. This is the task's scale convention, not a measured claim about the source scene. Infer the rest of the dimensions from the image. Use metres and Z up. Match the visible composition, materials and lighting; complete unseen areas plausibly. Keep major objects independently editable and pack texture dependencies. Build genuine geometry, not a single image plane. No original asset, exact mesh topology, object names or hidden dimensions are required.

Choose a perspective main camera to match the supplied view. Create an alternate camera by translating it 0.30 m along its local positive X axis, keeping lens and rotation unchanged. Both cameras and both renders must use the same scene. Render 800 by 450 pixels with Cycles, Standard view transform, exposure 0 and gamma 1. The alternate view has no target image; it checks three-dimensional consistency.

Use only the supplied task inputs to establish this particular scene. Do not retrieve its original source model, an untouched copy of the source scene, or additional source views from the internet.

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

Set `bench_role="scale_anchor"` for the foreground desk tabletop. Use scale_support for the actual supporting floor, balcony deck or ground beneath that anchor. Height is measured from its top surface to the local support surface, not world Z=0.
