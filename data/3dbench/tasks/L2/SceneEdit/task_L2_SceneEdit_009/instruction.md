The open freight wagon between the green locomotive and the flatbed wagon is missing. Rebuild it to match input/reference.png. Include the rectangular open-topped cargo box with visible inner walls and rim thickness, a lower chassis, the visible wheelsets and the coupling structures at both ends. Match its length and height to the two surviving vehicles and place the wheels on the same pair of rails. Preserve enough separation between wagon bodies for the couplings; do not fill the opening with a solid block or leave wheels floating above the track. Match the muted gray metal, restrained edge bevels and low-poly style. Keep the locomotive, flatbed, tanker on the other track, rails, sleepers, platform, canopy, warehouse and cargo crates unchanged. No train movement or physical coupling simulation is required.

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
