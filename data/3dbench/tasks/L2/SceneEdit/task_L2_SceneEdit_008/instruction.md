The pit buildings and covered grandstand have been removed from this stylized raceway. Rebuild the arrangement shown in input/reference.png: three adjoining pit garages along one side of the straight, an office block at the end of that row, and a separate covered stepped grandstand on the opposite side. Restore the garage bays facing the track with recessed openings, dividing piers and a continuous roof line. The office should read as a distinct end section with its visible window band. The grandstand needs individual seating tiers, supporting side walls, an open viewing face and an overhanging roof with real thickness and support. Align the structures with the surviving track, barriers and start gantry, preserving the gaps needed to enter the garage bays and keeping the racing surface unobstructed. Match the light concrete, red accent surfaces, dark glazing and compact cartoon proportions. Tiny signs may be simplified into colour blocks. Do not change the cars, road, barriers, gantry, terrain, camera or lights.

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
