The front service counter and the coffee machine on it have been removed from this small cartoon cafe. Restore them from input/reference.png. Build the long paneled counter, its continuous light-coloured top and rounded ends, then recreate the compact coffee machine with a main housing, projecting brew area, drip tray and visible controls. The counter must stand on the floor and the machine must rest on the countertop. Use the surviving rear cabinets, refrigerator and seating as scale and placement context. Leave the service passage behind the counter clear and preserve the customer route beside it. Match the restrained wood and pale-blue material palette and the simple beveled style. Do not alter the surviving cabinetry, furniture, walls, plants or lighting.

Start from input/initial.blend and use the single supplied reference image. Preserve everything outside the permitted changes described above, including all cameras, render and colour-management settings. Render main.png from the supplied main camera. For alternate.png, copy that camera and translate it 0.30 m along its local positive X axis without changing its rotation or lens. Keep both cameras and the same edited scene in scene.blend. Pack all dependencies. Do not replace the scene with a reference image plane or retrieve the original complete scene from the internet. Hidden details may be inferred plausibly. Retain the original scene scale and Z-up orientation.

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

## Procedural-material contract

Use the supplied procedural-material initial scene and reference image.
Preserve the supplied initial scene and its permitted edit scope. Use solid colors or procedural shading nodes only. Image
textures, environment images, image-dependent geometry/modifiers and image
compositing are prohibited, including packed or generated image maps and image
nodes retained in used node trees.
The reference picture is a visual guide, not a material asset for rendering.
Retain all original edit permissions, camera and render settings.
