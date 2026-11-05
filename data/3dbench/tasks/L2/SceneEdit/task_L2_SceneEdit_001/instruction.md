The bathtub has been removed from the supplied bathroom scene. Restore it to match input/reference.png: rebuild the curved outer shell, the recessed bathing cavity and the continuous rounded rim. Pay particular attention to the transition from the inner wall to the rim, the visible wall thickness and how the tub fits the retained feet above the floor. Match its location and size to the surrounding fixtures, window and vanity. The result should read as a hollow sanitary fixture, not a solid rounded block. Retain the existing feet, the cloth inside the tub, the taps and other bathroom fittings; do not duplicate them.

Start from input/initial.blend. Use the existing geometry as the scale and placement context, and use the single supplied image as the appearance reference. Keep all existing non-target geometry, world transforms, materials, textures, lights and camera settings unchanged. Add independently editable three-dimensional geometry for the missing object; do not substitute an image plane or a projection of the full reference photograph. Small hidden details may be completed plausibly rather than copied from an unavailable original model. Use metres and Z up, and pack any new texture dependencies into the scene.

Render output/main.png from the supplied main camera, preserving the scene's Cycles, resolution, exposure and color-management settings. Render output/alternate.png from a second camera translated 0.30 m to the right along the main camera's local X axis, with the same rotation and lens. Keep both cameras in output/scene.blend. Both renders must come from the same edited scene. The alternate view is a structural check and has no supplied target image.

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
