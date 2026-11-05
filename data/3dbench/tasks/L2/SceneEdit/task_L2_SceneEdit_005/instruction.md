The illumination of this snowy landscape has become excessively dim and blue. Restore the balance in input/reference.png: readable foreground rider and horse, textured snow, a softer distant fortress and mountains, and the bright breaks in the cloudy sky. Adjust only colors and energies of existing light objects and the existing world background strength. Keep the world texture and node connections, light positions, sizes and directions, all geometry and materials, volumetric settings, camera, saved frame, exposure and compositor unchanged. Do not add lights. Recover regional contrast and plausible cast shadows without clipping the snow or turning the rider into a uniformly bright silhouette.

Start from input/initial.blend. Use the single reference image. Preserve all scene data outside the changes explicitly allowed above, including cameras and render/color settings. Render main.png from the supplied camera. Duplicate that camera and move it 0.30 m along its local positive X axis without changing lens or rotation to render alternate.png. Keep both cameras in the same edited scene. Pack all dependencies. Hidden details may be completed plausibly.

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

## Procedural-material contract

Use the supplied procedural-material initial scene and reference image.
Preserve the supplied initial scene and its permitted edit scope. Use solid colors or procedural shading nodes only. Image
textures, environment images, image-dependent geometry/modifiers and image
compositing are prohibited, including packed or generated image maps and image
nodes retained in used node trees.
The reference picture is a visual guide, not a material asset for rendering.
Retain all original edit permissions, camera and render settings.

The supplied rig and terrain are prepared in a static pose. Preserve the supplied pose, skinning, explicit static meshes and remaining hair/particle systems. No animation reconstruction is required.
