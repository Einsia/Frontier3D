Reconstruct the object from input/reference.png and the three orthographic views input/front.png, input/side.png and input/top.png. All four images show the same assembled object. Model the pressurised cabin and window recesses, side access hatch, external equipment, undercarriage, repeated wheel modules and their articulated supports. Match the body-to-wheel proportions, layered suspension clearances and the curved cabin shell. Keep each wheel module as an editable group.

Use Blender to create genuinely three-dimensional geometry with separately editable semantic components. You may use a hierarchy of objects or clearly separable mesh islands; do not merge everything into an opaque unstructured lump or use a single image plane. Visible holes, gaps, thin structures, attachment points and overlapping layers matter. Exact source topology, manufacturer internals and tiny text or logos are not required. Complete unseen surfaces plausibly and do not add hidden machinery solely because it might exist in a real product. This is a static display reconstruction; mechanical operation, electronics and physics simulation are not required.

Use a maximum overall span of 1000.000 mm as the task scale convention, with a 2% tolerance. This is a reconstruction scale, not a claim about the real product's measured size. Infer the remaining proportions from the provided images. Export in metres with Z up. Keep rigid components free of gross intersections and floating attachments, while allowing intended joints and flexible cables. Match the dominant materials, colours and visible surface character; fine wear may be simplified without losing material identity.

At frame 1 save the assembled pose. At frame 61 provide a readable exploded arrangement separating the major semantic groups without changing their geometry; choose useful directions and spacing yourself. Returning to frame 1 must restore the assembly. Export scene.glb in the assembled state. Render main.png at 1000 by 1000 pixels using a camera matching the supplied primary image, with neutral studio lighting, Cycles, AgX and exposure 0. Keep the view and lighting in scene.blend. Do not retrieve the source model or any additional source views from the internet.

## Submission contract
Place every deliverable under `output/` in the task workspace. The evaluator will read these exact paths:

```text
output/
  solution.py       # reproducible Blender generation or editing entry point
  scene.blend       # editable native scene
  scene.glb         # assembled/exported result
  main.png          # required assembled view
  README.md         # short dependency and execution note
  assets/           # optional local textures or other files needed at runtime
```

Run the entry point from a clean copy with Blender in background mode:
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`
The script must resolve helper files relative to itself, read task data only from the supplied `input/` files and its own `output/assets/` (bundled helper code and installed libraries are allowed), and write or refresh the required outputs in `output/`. The supplied initial `.blend`, when present, is allowed. Do not rely on previously generated output files or hard-coded personal paths; pack textures into the saved scene or use portable relative paths under `output/assets/`. Keep the required output filenames exactly as shown; optional renders or logs go under `output/renders/` or `output/logs/`.

## Materials

Use solid colors or procedural materials only. Reference images are for observation. Do not use bitmap textures, HDRIs, baked/generated images, or image-driven shaders, lights, geometry nodes or compositing. Procedural Noise and Bump nodes are allowed.
